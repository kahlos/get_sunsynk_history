import requests
import json
import argparse
from datetime import datetime, timedelta, date
import csv
import time
from collections import defaultdict
import os
import sys       # Needed for sys.argv check
import getpass   # For secure password prompt
import configparser
import platform  # For OS-specific config path

# --- Configuration ---
CONFIG_FILENAME = "config.ini"                  # Renamed config file
CONFIG_DIR_NAME = "get-sunsynk-history"       # Renamed config folder

# Choose appropriate config path based on OS
if platform.system() == "Windows":
    APP_CONFIG_DIR = os.path.join(os.getenv('APPDATA', ''), CONFIG_DIR_NAME)
elif platform.system() == "Darwin": # macOS
    APP_CONFIG_DIR = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', CONFIG_DIR_NAME)
else: # Linux and other Unix-like
    APP_CONFIG_DIR = os.path.join(os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), CONFIG_DIR_NAME)

CONFIG_FILE_PATH = os.path.join(APP_CONFIG_DIR, CONFIG_FILENAME)

# API Details
BASE_URL = "https://api.sunsynk.net"
LOGIN_URL = f"{BASE_URL}/oauth/token"
PLANTS_URL = f"{BASE_URL}/api/v1/plants"
DAILY_ENERGY_URL_TEMPLATE = f"{BASE_URL}/api/v1/plant/energy/{{plant_id}}/day"
CLIENT_ID = "csp-web"
REQUEST_DELAY = 0.6 # Seconds to wait between API calls

# --- Helper Functions ---

def print_usage_and_exit(parser):
    """Prints custom usage help and exits."""
    print("Usage: python get_sunsynk_history.py [DATE_1] [DATE_2] [-o OUTPUT_DIR]")
    print("\nFetches historical data from the Sunsynk API (limited to the last ~90 days).")
    print("\nArguments:")
    print("  DATE_1       (Optional) Start date (YYYY-MM-DD). If only DATE_1 is provided,")
    print("               fetches from yesterday back to DATE_1.")
    print("  DATE_2       (Optional) End date (YYYY-MM-DD). Requires DATE_1.")
    print("  -o OUTPUT_DIR (Optional) Directory to save the output CSV file")
    print("               (default: current directory).")
    print("\nBehavior:")
    print("  - No dates provided: Fetches data for the CURRENT DAY.")
    print("  - One date provided: Fetches data from YESTERDAY back to the specified DATE_1.")
    print("  - Two dates provided: Fetches data for the inclusive range DATE_1 to DATE_2.")
    print("\nCredentials:")
    print("  The script reads credentials in this order:")
    print("  1. Environment Variables: SUNSYNK_USERNAME, SUNSYNK_PASSWORD")
    print(f"  2. Config File: {CONFIG_FILE_PATH}")
    print("     (Create this file with a [Credentials] section containing Username and Password)")
    print("  3. Secure Prompt: If not found above, you will be prompted.")
    print("     (Credentials entered via prompt will be saved to the config file if possible).")
    print("\n")
    #parser.print_help() # Optionally print standard argparse help too
    sys.exit(0)

def get_credentials():
    """Gets username and password from Env -> Config File -> Prompt."""
    username = os.getenv("SUNSYNK_USERNAME")
    password = os.getenv("SUNSYNK_PASSWORD")
    source = "Environment Variables"
    save_creds = False # Flag to indicate if we should try saving prompted creds

    if not (username and password):
        source = f"Config File ({CONFIG_FILE_PATH})"
        # print(f"\nCredentials not found in environment variables, trying config file: {CONFIG_FILE_PATH}")
        config = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                config.read(CONFIG_FILE_PATH)
                username = config.get('Credentials', 'Username', fallback=None)
                password = config.get('Credentials', 'Password', fallback=None)
                if not (username and password):
                    print(f"  -> Username or Password missing in config file ({CONFIG_FILE_PATH}).")
                    username, password = None, None
                else:
                    print(f"  -> Credentials loaded from config file: {CONFIG_FILE_PATH}")
            except Exception as e:
                print(f"  -> Error reading config file ({CONFIG_FILE_PATH}): {e}")
                username, password = None, None
        else:
            print(f"  -> Config file not found: {CONFIG_FILE_PATH}")
            username, password = None, None

    if not (username and password):
        source = "User Prompt"
        print("\nCredentials not found in environment or config file.")
        try:
            username = input("Enter Sunsynk Username (email): ")
            password = getpass.getpass("Enter Sunsynk Password: ")
            if username and password:
                save_creds = True # Mark creds from prompt to be saved
            else:
                print("Error: Username and password cannot be empty.")
                return None, None, None
        except EOFError: # Handle case where script is run non-interactively without creds
             print("\nError: Could not read credentials from prompt (non-interactive run?).")
             print("Please provide credentials via environment variables or config file.")
             return None, None, None


    # --- Save prompted credentials if needed ---
    if save_creds:
        print(f"Using credentials provided by {source}.") # Confirm source before potential save message
        try:
            os.makedirs(APP_CONFIG_DIR, exist_ok=True)
            config = configparser.ConfigParser()
            config['Credentials'] = {}
            config['Credentials']['Username'] = username
            config['Credentials']['Password'] = password
            with open(CONFIG_FILE_PATH, 'w') as configfile:
                config.write(configfile)
            print(f"  -> Credentials saved to {CONFIG_FILE_PATH} for future use.")
        except Exception as e:
            print(f"  -> Warning: Could not save credentials to {CONFIG_FILE_PATH}. Error: {e}")
    elif username and password:
        print(f"Using credentials obtained from: {source}")
    else:
        print("Error: Username and Password are required.")
        return None, None, None

    return username, password, source

# --- Login, Get Plants, Format Value, Parse Timestamp functions ---
# (These remain the same as the previous version - include them here)
def login(username, password):
    """Authenticates with the API and returns the access token."""
    print(f"Attempting to log in to {LOGIN_URL}...")
    payload = {
        "username": username,
        "password": password,
        "grant_type": "password",
        "client_id": CLIENT_ID,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    try:
        response = requests.post(LOGIN_URL, headers=headers, json=payload, timeout=30) # Increased timeout
        response.raise_for_status() # Raise HTTP errors
        data = response.json()

        if data.get("success"):
            access_token = data.get("data", {}).get("access_token")
            if access_token:
                print("Login successful.")
                return access_token
            else:
                # Attempt to get more specific error msg if available
                error_msg = data.get('msg') or data.get('data', {}).get('error_description') or 'Access token not found'
                print(f"Login failed: {error_msg}")
                return None
        else:
             error_msg = data.get('msg') or data.get('data', {}).get('error_description') or 'Unknown error'
             print(f"Login failed: {error_msg}")
             return None

    except requests.exceptions.HTTPError as e:
        error_body = e.response.text
        error_msg_detail = ""
        try: # Try to get specific error from API response body
            error_data = json.loads(error_body)
            error_msg_detail = error_data.get('msg') or error_data.get('error_description') or error_data.get('message') or error_body
        except json.JSONDecodeError:
            error_msg_detail = error_body
        print(f"Login HTTP error: {e.response.status_code} - {error_msg_detail[:500]}") # Limit length
        return None
    except requests.exceptions.RequestException as e:
        print(f"Login network/request error: {e}")
        return None
    except json.JSONDecodeError:
        print(f"Login error: Could not decode JSON response from {LOGIN_URL}.")
        print("Raw response:", response.text)
        return None

def get_plants(access_token):
    """Fetches plant information."""
    # (Same as before)
    print(f"Fetching plant information from {PLANTS_URL}...")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    try:
        response = requests.get(PLANTS_URL, headers=headers, params={"page": 1, "limit": 10}, timeout=20)
        response.raise_for_status()
        data = response.json()

        if data.get("success") and "data" in data and "infos" in data["data"]:
             plants = data["data"]["infos"]
             if not plants:
                 print("No plants found for this account.")
                 return None
             print(f"Found {len(plants)} plant(s).")
             return plants
        else:
            print(f"Failed to get plants: {data.get('msg', 'Unknown error')}")
            return None

    except requests.exceptions.HTTPError as e:
        print(f"Error fetching plants (HTTP {e.response.status_code}): {e.response.text}")
        if e.response.status_code == 401: print("-> Token might be invalid or expired.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching plants: {e}")
        return None
    except json.JSONDecodeError:
        print("Error fetching plants: Could not decode JSON response.")
        print("Raw response:", response.text)
        return None

def format_value(value_str):
    """Formats numeric string, removing '.0' for integers."""
    # (Same as before)
    if value_str is None:
        return ""
    try:
        num = float(value_str)
        if num.is_integer():
            return str(int(num))
        else:
            # Keep precision as returned by API if not integer
            return str(num) # Use str(num) instead of value_str to handle float conversion result
    except (ValueError, TypeError):
        return str(value_str) # Ensure return is string

def parse_api_timestamp(date_part: date, time_part_str: str) -> datetime | None:
    """Combines date and time string parts into a datetime object."""
    # (Same as before)
    if not time_part_str: return None
    time_formats = ["%H:%M:%S", "%H:%M"] # Try with seconds first
    parsed_time = None
    for fmt in time_formats:
        try:
            parsed_time = datetime.strptime(time_part_str, fmt).time()
            break # Stop if parsed successfully
        except ValueError:
            continue # Try next format

    if parsed_time is None:
        print(f"  - Warning: Could not parse time string '{time_part_str}' with known formats.")
        return None

    return datetime.combine(date_part, parsed_time)
# -------------------------------------------------------------------

def get_daily_energy_data_restructured(access_token, plant_id, target_date):
    """
    Fetches energy data and restructures it.
    Returns a dict keyed by datetime object, value is {label[unit]: formatted_value}.
    """
    # (Same logic as previous version, uses the updated parse_api_timestamp)
    date_str = target_date.strftime("%Y-%m-%d")
    url = DAILY_ENERGY_URL_TEMPLATE.format(plant_id=plant_id)
    print(f"Fetching data: Plant {plant_id}, Date {date_str}...")
    # (Rest of the function is the same as previous 'get_daily_energy_data_restructured')

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    params = {
        "date": date_str,
        "id": plant_id,
        "lan": "en"
    }
    data_by_datetime = defaultdict(dict) # Store {datetime_object: {label_unit: value}}

    try:
        time.sleep(REQUEST_DELAY)
        response = requests.get(url, headers=headers, params=params, timeout=60) # Even longer timeout
        response.raise_for_status()
        data = response.json()

        if data.get("success") and "data" in data and "infos" in data["data"]:
            infos = data["data"]["infos"]
            if not infos:
                print(f"  - OK: No specific data ('infos') returned by API for {date_str}.")
                return None

            all_labels_units_day = set()
            records_found_for_day = False
            for info_item in infos:
                label = info_item.get('label')
                unit = info_item.get('unit', '')
                records = info_item.get('records', [])
                if not label: continue

                header_name = f"{label}[{unit}]" if unit else label
                all_labels_units_day.add(header_name)

                if not records: continue # No records for this label, skip to next label

                records_found_for_day = True # Mark that we found some records today
                for record in records:
                    record_time_str = record.get('time')
                    record_value_str = record.get('value')

                    # --- Key change: Use combined datetime ---
                    datetime_key = parse_api_timestamp(target_date, record_time_str)
                    # ---------------------------------------

                    if datetime_key and record_value_str is not None:
                        formatted_val = format_value(record_value_str)
                        data_by_datetime[datetime_key][header_name] = formatted_val
                    # else: print(f"  - Skipping record, invalid time/value for '{label}': {record}")

            if data_by_datetime:
                 # Sort the labels for consistent printing
                sorted_labels = sorted(list(all_labels_units_day))
                print(f"  + OK: Fetched {len(data_by_datetime)} timestamp entries for {date_str} with labels: {', '.join(sorted_labels)}")
                return dict(data_by_datetime) # Convert defaultdict to dict
            elif records_found_for_day:
                 print(f"  - Warning: Found records for {date_str}, but failed to parse valid timestamps or values.")
                 return None
            else:
                 print(f"  - OK: No valid measurement records found within the 'infos' structure for {date_str}.")
                 return None # No valid data points parsed

        else:
            msg = data.get('msg', 'No data structure or unknown error')
            print(f"  - API Fail/No Data for {date_str}: {msg}")
            # If API says success=false but status was 200, log it
            if not data.get("success", True) and response.status_code == 200:
                 print(f"     (API success=false, HTTP Status=200. Raw response: {data})")
            return None

    except requests.exceptions.HTTPError as e:
        print(f"  - HTTP error {e.response.status_code} fetching for {date_str}: {e.response.text[:200]}") # Truncate long errors
        if e.response.status_code == 401:
             print("  -> Authentication error. Stopping.")
             raise ConnectionAbortedError("Token expired or invalid")
        elif e.response.status_code == 429:
             print("  -> Rate limited! Increase REQUEST_DELAY (currently {REQUEST_DELAY}s).")
        # Handle other specific errors if needed
        return None # Allow loop to continue for other days unless it's auth error
    except requests.exceptions.RequestException as e:
        print(f"  - Network/request error fetching for {date_str}: {e}")
        return None
    except json.JSONDecodeError:
        print(f"  - Error decoding energy data JSON for {date_str}.")
        print("  - Raw response snippet:", response.text[:200] + ('...' if len(response.text) > 200 else ''))
        return None

# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(
        description="Extract historical data from Sunsynk API (limited to last 90 days by API).",
        epilog="Handles dates, credentials, and formats output to a wide CSV."
    )
    parser.add_argument("dates", nargs='*', help="Date(s) in YYYY-MM-DD format (optional).")
    parser.add_argument("-o", "--outputdir", default=".",
                        help="Output directory (default: current directory)")
    # If run with no arguments (only script name), print custom help
    if len(sys.argv) == 1:
        print_usage_and_exit(parser)

    args = parser.parse_args()

    username, password, cred_source = get_credentials()
    if not (username and password):
        print("Exiting: Failed to obtain credentials.")
        return

    # --- Determine Date Range ---
    today = date.today()
    start_dt = None
    end_dt = None
    filename_mode = ""

    try:
        if len(args.dates) == 0:
            # Today's data
            start_dt = today
            end_dt = today
            filename_mode = "today"
            print(f"\nFetching data for today: {start_dt.strftime('%Y-%m-%d')}")
        elif len(args.dates) == 1:
            # Yesterday back to Date 1
            start_dt = datetime.strptime(args.dates[0], "%Y-%m-%d").date()
            end_dt = today - timedelta(days=1)
            filename_mode = "range"
            print(f"\nFetching data from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} (yesterday)")
        elif len(args.dates) == 2:
            # Specific range
            start_dt = datetime.strptime(args.dates[0], "%Y-%m-%d").date()
            end_dt = datetime.strptime(args.dates[1], "%Y-%m-%d").date()
            filename_mode = "range"
            print(f"\nFetching data from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
        else:
            print("Error: Too many date arguments.")
            print_usage_and_exit(parser) # Show help if args are wrong

        # Ensure start <= end
        if start_dt > end_dt:
            print(f"Warning: Start date ({start_dt}) is after end date ({end_dt}). Swapping them for fetching.")
            start_dt, end_dt = end_dt, start_dt

        # Store effective range for filename
        effective_start_str = start_dt.strftime("%Y-%m-%d")
        effective_end_str = end_dt.strftime("%Y-%m-%d")

    except ValueError:
        print("Error: Invalid date format in arguments. Please use YYYY-MM-DD.")
        return

    # --- 90-Day Warning ---
    ninety_days_ago = today - timedelta(days=90)
    if start_dt < ninety_days_ago:
        print(f"\nWarning: Requested start date {start_dt.strftime('%Y-%m-%d')} is older than 90 days ago ({ninety_days_ago.strftime('%Y-%m-%d')}).")
        print("         API data may not be available this far back.")

    # --- API Interaction ---
    access_token = login(username, password)
    if not access_token: print("Exiting."); return

    plants = get_plants(access_token)
    if not plants: print("Exiting."); return

    # --- Plant Selection ---
    # (Same selection logic as previous version)
    target_plant_id = None
    target_plant_name = None
    if len(plants) == 1:
         target_plant_id = plants[0]['id']
         target_plant_name = plants[0]['name']
         print(f"\nFound 1 plant: Using ID={target_plant_id}, Name='{target_plant_name}'")
    else:
         print("\nMultiple plants found:")
         for i, plant in enumerate(plants):
              print(f"  {i+1}: ID={plant['id']}, Name='{plant['name']}'")
         while target_plant_id is None:
              try:
                   choice = input(f"Enter the number of the plant to export (1-{len(plants)}): ")
                   plant_index = int(choice) - 1
                   if 0 <= plant_index < len(plants):
                        target_plant_id = plants[plant_index]['id']
                        target_plant_name = plants[plant_index]['name']
                        print(f"Selected Plant: ID={target_plant_id}, Name='{target_plant_name}'")
                   else:
                        print("Invalid choice.")
              except ValueError:
                   print("Invalid input. Please enter a number.")
              except EOFError:
                    print("\nInput aborted. Exiting.")
                    return

    if not target_plant_id: return # Exit if selection failed

    # --- Fetch Data ---
    all_data_by_datetime = {} # Use datetime objects as keys
    all_headers = set()
    print(f"\nStarting data fetch loop from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}...")

    current_loop_date = start_dt
    fetch_interrupted = False
    while current_loop_date <= end_dt:
        try:
            daily_data_dict = get_daily_energy_data_restructured(access_token, target_plant_id, current_loop_date)
            if daily_data_dict:
                all_data_by_datetime.update(daily_data_dict)
                # Dynamically collect all headers seen
                for timestamp_data in daily_data_dict.values():
                    all_headers.update(timestamp_data.keys())
        except ConnectionAbortedError: # Raised on 401
            print("Stopping data fetch loop due to authentication failure.")
            fetch_interrupted = True
            all_data_by_datetime = {} # Clear potentially bad data
            break # Exit date loop

        current_loop_date += timedelta(days=1)

    # --- Write to CSV ---
    if fetch_interrupted or not all_data_by_datetime:
        print("\nNo data collected or fetch aborted. CSV file will not be created.")
        return
    if not all_headers:
         print("\nNo measurement labels found in the collected data. Cannot create CSV.")
         return

    # Prepare headers and filename
    sorted_unique_headers = sorted(list(all_headers))
    final_fieldnames = ["DateTime"] + sorted_unique_headers

    if filename_mode == "today":
         # Handle case where today's data was fetched
         output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}_today.csv"
    elif effective_start_str == effective_end_str: # Single specific day requested or defaulted to
         output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}.csv"
    else:
         output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}_to_{effective_end_str}.csv"

    output_path = os.path.join(args.outputdir, output_filename)
    print(f"\nData fetch complete. Writing {len(all_data_by_datetime)} timestamp records to {output_path}...")
    print(f"   (Note: Gaps in timestamps may exist if the API didn't provide data for every 5-min interval).")

    # Create output dir if needed
    try:
        os.makedirs(args.outputdir, exist_ok=True)
    except OSError as e:
        print(f"Error creating output directory '{args.outputdir}': {e}")
        return

    try:
        # Sort final data by datetime keys
        sorted_datetimes = sorted(all_data_by_datetime.keys())

        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=final_fieldnames)
            writer.writeheader()

            for dt_key in sorted_datetimes:
                timestamp_data = all_data_by_datetime[dt_key]
                row_to_write = {"DateTime": dt_key.strftime("%Y-%m-%d %H:%M:%S")}
                row_to_write.update(timestamp_data)
                writer.writerow(row_to_write)

        print(f"Data successfully written to {output_path}")

    except IOError as e:
        print(f"Error writing CSV file '{output_path}': {e}")
    except KeyError as e:
         print(f"CSV writing error: Missing key {e}.")


if __name__ == "__main__":
    main()