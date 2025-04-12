import requests
import json
import argparse
from datetime import datetime, timedelta, date
import csv
import time
from collections import defaultdict
import os
import sys
import getpass
import configparser
import platform

# --- Configuration ---
CONFIG_FILENAME = "config.ini"
CONFIG_DIR_NAME = "get-sunsynk-history" # Directory name updated

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
REQUEST_DELAY = 0.6 # Seconds

# --- Helper Functions (get_credentials, login, get_plants, format_value, parse_api_timestamp) ---
# Include the latest versions of these functions from the previous response here...
# (They are the same as the last version provided)
def get_credentials():
    """Gets username and password from Env -> Config File -> Prompt."""
    username = os.getenv("SUNSYNK_USERNAME")
    password = os.getenv("SUNSYNK_PASSWORD")
    source = "Environment Variables"
    save_creds = False

    if not (username and password):
        source = f"Config File ({CONFIG_FILE_PATH})"
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
            # Only print not found if we didn't get creds from Env
            if not os.getenv("SUNSYNK_USERNAME"):
                 print(f"  -> Config file not found: {CONFIG_FILE_PATH}")
            username, password = None, None

    if not (username and password):
        source = "User Prompt"
        print("\nCredentials not found in environment or config file.")
        try:
            username = input("Enter Sunsynk Username (email): ")
            password = getpass.getpass("Enter Sunsynk Password: ")
            if username and password:
                save_creds = True
            else:
                print("Error: Username and password cannot be empty.")
                return None, None, None
        except EOFError:
             print("\nError: Could not read credentials from prompt (non-interactive run?).")
             print("Please provide credentials via environment variables or config file.")
             return None, None, None

    if save_creds:
        print(f"Using credentials provided by {source}.")
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
        response = requests.post(LOGIN_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("success"):
            access_token = data.get("data", {}).get("access_token")
            if access_token:
                print("Login successful.")
                return access_token
            else:
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
        try:
            error_data = json.loads(error_body)
            error_msg_detail = error_data.get('msg') or error_data.get('error_description') or error_data.get('message') or error_body
        except json.JSONDecodeError:
            error_msg_detail = error_body
        print(f"Login HTTP error: {e.response.status_code} - {error_msg_detail[:500]}")
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
    if value_str is None: return ""
    try:
        num = float(value_str)
        return str(int(num)) if num.is_integer() else str(num)
    except (ValueError, TypeError): return str(value_str)

def parse_api_timestamp(date_part: date, time_part_str: str) -> datetime | None:
    """Combines date and time string parts into a datetime object."""
    if not time_part_str: return None
    time_formats = ["%H:%M:%S", "%H:%M"]
    parsed_time = None
    for fmt in time_formats:
        try:
            parsed_time = datetime.strptime(time_part_str, fmt).time(); break
        except ValueError: continue
    if parsed_time is None:
        # print(f"  - Warning: Could not parse time string '{time_part_str}'") # Can be noisy
        return None
    return datetime.combine(date_part, parsed_time)

def get_daily_energy_data_restructured(access_token, plant_id, target_date):
    """Fetches and restructures energy data for a specific day."""
    # (Same fetch and restructure logic as the previous version)
    date_str = target_date.strftime("%Y-%m-%d")
    url = DAILY_ENERGY_URL_TEMPLATE.format(plant_id=plant_id)
    print(f"Fetching data: Plant {plant_id}, Date {date_str}...")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    params = {"date": date_str, "id": plant_id, "lan": "en"}
    data_by_datetime = defaultdict(dict)

    try:
        time.sleep(REQUEST_DELAY)
        response = requests.get(url, headers=headers, params=params, timeout=60)
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
                label = info_item.get('label'); unit = info_item.get('unit', '')
                records = info_item.get('records', [])
                if not label: continue
                header_name = f"{label}[{unit}]" if unit else label
                all_labels_units_day.add(header_name)
                if not records: continue
                records_found_for_day = True

                for record in records:
                    record_time_str = record.get('time'); record_value_str = record.get('value')
                    datetime_key = parse_api_timestamp(target_date, record_time_str)
                    if datetime_key and record_value_str is not None:
                        data_by_datetime[datetime_key][header_name] = format_value(record_value_str)

            if data_by_datetime:
                sorted_labels = sorted(list(all_labels_units_day))
                print(f"  + OK: Fetched {len(data_by_datetime)} timestamps for {date_str} ({', '.join(sorted_labels[:3])}{'...' if len(sorted_labels)>3 else ''})")
                return dict(data_by_datetime)
            elif records_found_for_day:
                 print(f"  - Warning: Found records structure for {date_str}, but no valid timestamps/values parsed.")
                 return None
            else:
                 print(f"  - OK: No measurement records found within 'infos' for {date_str}.")
                 return None

        else:
            msg = data.get('msg', 'No data structure or unknown error')
            print(f"  - API Fail/No Data for {date_str}: {msg}")
            if not data.get("success", True) and response.status_code == 200:
                 print(f"     (API success=false, HTTP Status=200. Raw response: {data})")
            return None

    except requests.exceptions.HTTPError as e:
        print(f"  - HTTP error {e.response.status_code} fetching for {date_str}: {e.response.text[:200]}")
        if e.response.status_code == 401: raise ConnectionAbortedError("Token expired or invalid")
        elif e.response.status_code == 429: print(f"  -> Rate limited! Consider increasing REQUEST_DELAY (currently {REQUEST_DELAY}s).")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  - Network/request error fetching for {date_str}: {e}")
        return None
    except json.JSONDecodeError:
        print(f"  - Error decoding JSON for {date_str}. Raw response snippet:", response.text[:200] + ('...' if len(response.text) > 200 else ''))
        return None
# -------------------------------------------------------------------


# --- Main Execution ---

def main():
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Extract historical data from Sunsynk API.",
        epilog=f"""Fetches data (limited to the last ~90 days by API).
Modes:
  No dates   : Fetches CURRENT DAY's data.
  One date   : Fetches YESTERDAY back to the specified date.
  Two dates  : Fetches the specified inclusive range.

Credentials Priority: Env Vars -> Config File -> Prompt.
Config File Path: {CONFIG_FILE_PATH}
""",
        formatter_class=argparse.RawTextHelpFormatter # Keep newlines in epilog
    )
    parser.add_argument("dates", nargs='*', # 0, 1, or 2 dates
                        help="Date(s) (YYYY-MM-DD). See usage modes below.")
    parser.add_argument("-o", "--outputdir", default=".",
                        help="Output directory for the CSV file (default: current directory).")
    parser.add_argument("--force", action="store_true",
                        help="Force fetching data even if the start date is older than 90 days (API may return no data).")
    args = parser.parse_args()

    # --- Get Credentials ---
    username, password, cred_source = get_credentials()
    if not (username and password):
        print("Exiting: Could not obtain credentials.")
        return

    # --- Determine Date Range ---
    today = date.today()
    start_dt = None
    end_dt = None
    filename_mode = ""

    try:
        if len(args.dates) == 0:
            start_dt = today
            end_dt = today
            filename_mode = "today"
            print(f"\nMode: Fetching data for today ({start_dt.strftime('%Y-%m-%d')})")
        elif len(args.dates) == 1:
            start_dt = datetime.strptime(args.dates[0], "%Y-%m-%d").date()
            end_dt = today - timedelta(days=1)
            filename_mode = "range"
            print(f"\nMode: Fetching data from {start_dt.strftime('%Y-%m-%d')} to yesterday ({end_dt.strftime('%Y-%m-%d')})")
        elif len(args.dates) == 2:
            start_dt = datetime.strptime(args.dates[0], "%Y-%m-%d").date()
            end_dt = datetime.strptime(args.dates[1], "%Y-%m-%d").date()
            filename_mode = "range"
            print(f"\nMode: Fetching data for specified range ({start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')})")
        # Argparse handles > 2 dates by default error

        if start_dt > end_dt:
            print(f"Warning: Start date ({start_dt}) is after end date ({end_dt}). Swapping them.")
            start_dt, end_dt = end_dt, start_dt

        effective_start_str = start_dt.strftime("%Y-%m-%d")
        effective_end_str = end_dt.strftime("%Y-%m-%d")

    except ValueError:
        print("Error: Invalid date format in arguments. Please use YYYY-MM-DD.")
        return

    # --- 90-Day Limit Check ---
    ninety_days_ago = today - timedelta(days=90)
    if start_dt < ninety_days_ago:
        if not args.force:
            print(f"\nError: Start date {start_dt.strftime('%Y-%m-%d')} is older than 90 days ({ninety_days_ago.strftime('%Y-%m-%d')}).")
            print("       The API likely has no data this old.")
            print("       Use the --force flag to attempt fetching anyway.")
            sys.exit(1) # Exit if too old and not forced
        else:
            print(f"\nWarning: Start date {start_dt.strftime('%Y-%m-%d')} is older than 90 days.")
            print("         Proceeding due to --force flag, but the API may return no data for older dates.")

    # --- API Interaction ---
    access_token = login(username, password)
    if not access_token: print("Exiting."); return

    plants = get_plants(access_token)
    if not plants: print("Exiting."); return

    # --- Plant Selection ---
    # (Same logic as before)
    target_plant_id = None
    target_plant_name = None
    if len(plants) == 1:
         target_plant_id = plants[0]['id']
         target_plant_name = plants[0]['name']
         print(f"\nFound 1 plant: Using ID={target_plant_id}, Name='{target_plant_name}'")
    else:
         print("\nMultiple plants found:")
         for i, plant in enumerate(plants): print(f"  {i+1}: ID={plant['id']}, Name='{plant['name']}'")
         while target_plant_id is None:
              try:
                   choice = input(f"Enter the number of the plant to export (1-{len(plants)}): ")
                   plant_index = int(choice) - 1
                   if 0 <= plant_index < len(plants):
                        target_plant_id = plants[plant_index]['id']; target_plant_name = plants[plant_index]['name']
                        print(f"Selected Plant: ID={target_plant_id}, Name='{target_plant_name}'")
                   else: print("Invalid choice.")
              except ValueError: print("Invalid input.")
              except EOFError: print("\nInput aborted."); return
    if not target_plant_id: return

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
                for ts_data in daily_data_dict.values(): all_headers.update(ts_data.keys())
        except ConnectionAbortedError:
            print("Stopping data fetch loop due to authentication failure.")
            fetch_interrupted = True; all_data_by_datetime = {}; break
        except KeyboardInterrupt:
            print("\nFetch interrupted by user.")
            fetch_interrupted = True; break # Allow partial write

        current_loop_date += timedelta(days=1)

    # --- Write to CSV ---
    if fetch_interrupted and not all_data_by_datetime:
        print("\nFetch aborted, no data collected. CSV file not created.")
        return
    if not all_data_by_datetime:
        print("\nNo data was successfully collected. CSV file will not be created.")
        return
    if not all_headers:
         print("\nNo measurement labels/headers found. Cannot create CSV.")
         return

    # Prepare headers and filename
    sorted_unique_headers = sorted(list(all_headers))
    final_fieldnames = ["DateTime"] + sorted_unique_headers

    if filename_mode == "today":
        # Use the actual date fetched, which is 'today'
        output_filename = f"sunsynk_plant_{target_plant_id}_{today.strftime('%Y-%m-%d')}_today.csv"
    elif effective_start_str == effective_end_str:
        output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}.csv"
    else:
         output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}_to_{effective_end_str}.csv"

    output_path = os.path.join(args.outputdir, output_filename)
    record_count = len(all_data_by_datetime)
    status_msg = " (fetch interrupted)" if fetch_interrupted else ""
    print(f"\nData fetch loop finished{status_msg}. Writing {record_count} timestamp records to {output_path}...")
    if record_count > 0:
        print(f"   (Note: Gaps in timestamps likely mean the API didn't report data for every interval).")

    try:
        os.makedirs(args.outputdir, exist_ok=True)
    except OSError as e:
        print(f"Error creating output directory '{args.outputdir}': {e}"); return

    try:
        sorted_datetimes = sorted(all_data_by_datetime.keys()) # Sort by datetime
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=final_fieldnames)
            writer.writeheader()
            for dt_key in sorted_datetimes:
                row_to_write = {"DateTime": dt_key.strftime("%Y-%m-%d %H:%M:%S")}
                row_to_write.update(all_data_by_datetime[dt_key])
                writer.writerow(row_to_write)
        print(f"Data successfully written to {output_path}")
    except IOError as e: print(f"Error writing CSV file '{output_path}': {e}")
    except KeyError as e: print(f"CSV writing error: Missing key {e}.")


if __name__ == "__main__":
    main()