import requests
import json
import argparse
from datetime import datetime, timedelta, date
import csv
import time
from collections import defaultdict
import os
import getpass # For secure password prompt
import configparser
import platform # For OS-specific config path

# --- Configuration ---
CONFIG_FILENAME = "credentials.ini"
CONFIG_DIR_NAME = "sunsynk"

# Choose appropriate config path based on OS
if platform.system() == "Windows":
    APP_CONFIG_DIR = os.path.join(os.getenv('APPDATA', ''), CONFIG_DIR_NAME)
elif platform.system() == "Darwin": # macOS
    APP_CONFIG_DIR = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', CONFIG_DIR_NAME)
else: # Linux and other Unix-like
    APP_CONFIG_DIR = os.path.join(os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), CONFIG_DIR_NAME)

CONFIG_FILE_PATH = os.path.join(APP_CONFIG_DIR, CONFIG_FILENAME)

# API Details
BASE_URL = "https://api.sunsynk.net" # <--- Updated Base URL
LOGIN_URL = f"{BASE_URL}/oauth/token"
PLANTS_URL = f"{BASE_URL}/api/v1/plants"
DAILY_ENERGY_URL_TEMPLATE = f"{BASE_URL}/api/v1/plant/energy/{{plant_id}}/day"
CLIENT_ID = "csp-web"
REQUEST_DELAY = 0.6 # Seconds to wait between API calls

# --- Helper Functions ---

def get_credentials():
    """Gets username and password from Env -> Config File -> Prompt."""
    username = os.getenv("SUNSYNK_USERNAME")
    password = os.getenv("SUNSYNK_PASSWORD")

    source = "Environment Variables"

    if not (username and password):
        source = f"Config File ({CONFIG_FILE_PATH})"
        print(f"\nCredentials not found in environment variables, trying config file: {CONFIG_FILE_PATH}")
        config = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                config.read(CONFIG_FILE_PATH)
                username = config.get('Credentials', 'Username', fallback=None)
                password = config.get('Credentials', 'Password', fallback=None)
                if not (username and password):
                    print("  -> Username or Password missing in config file.")
                    username, password = None, None # Reset if partially found
                else:
                    print("  -> Credentials successfully loaded from config file.")
            except Exception as e:
                print(f"  -> Error reading config file: {e}")
                username, password = None, None # Reset on error
        else:
            print("  -> Config file not found.")
            username, password = None, None

    if not (username and password):
        source = "User Prompt"
        print("\nCredentials not found in environment or config file.")
        username = input("Enter Sunsynk Username (email): ")
        password = getpass.getpass("Enter Sunsynk Password: ")

    if not (username and password):
        print("Error: Username and Password are required.")
        return None, None, None # Indicate failure

    print(f"Using credentials obtained from: {source}")
    return username, password, source

def login(username, password):
    # (Login function remains the same as previous version)
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
        response = requests.post(LOGIN_URL, headers=headers, json=payload, timeout=20)
        response.raise_for_status() # Raise HTTP errors
        data = response.json()

        if data.get("success"):
            access_token = data.get("data", {}).get("access_token")
            if access_token:
                print("Login successful.")
                return access_token
            else:
                print(f"Login failed: Access token not found in response. API Message: {data.get('msg')}")
                return None
        else:
            print(f"Login failed: {data.get('msg', 'Unknown error')}")
            return None

    except requests.exceptions.HTTPError as e:
        print(f"Login HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Login network/request error: {e}")
        return None
    except json.JSONDecodeError:
        print(f"Login error: Could not decode JSON response from {LOGIN_URL}.")
        print("Raw response:", response.text)
        return None

def get_plants(access_token):
    # (get_plants function remains the same as previous version)
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
    # (format_value function remains the same as previous version)
    if value_str is None:
        return ""
    try:
        num = float(value_str)
        if num.is_integer():
            return str(int(num))
        else:
            return value_str # Keep as original string if it has decimals
    except (ValueError, TypeError):
        return value_str

def parse_api_timestamp(date_part: date, time_part_str: str) -> datetime | None:
    """Combines date and time string parts into a datetime object."""
    if not time_part_str: return None
    try:
        time_obj = datetime.strptime(time_part_str, "%H:%M:%S").time() # Some API times lack seconds
    except ValueError:
         try:
              time_obj = datetime.strptime(time_part_str, "%H:%M").time() # Try without seconds
         except ValueError:
              print(f"  - Warning: Could not parse time string '{time_part_str}'")
              return None

    return datetime.combine(date_part, time_obj)


def get_daily_energy_data_restructured(access_token, plant_id, target_date):
    """
    Fetches energy data and restructures it.
    Returns a dict keyed by datetime object, value is {label[unit]: formatted_value}.
    """
    date_str = target_date.strftime("%Y-%m-%d")
    url = DAILY_ENERGY_URL_TEMPLATE.format(plant_id=plant_id)
    print(f"Fetching data: Plant {plant_id}, Date {date_str} (URL: {url}?date={date_str}...)")

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
        # Add delay
        time.sleep(REQUEST_DELAY)

        response = requests.get(url, headers=headers, params=params, timeout=45)
        response.raise_for_status()
        data = response.json()

        if data.get("success") and "data" in data and "infos" in data["data"]:
            infos = data["data"]["infos"]
            if not infos:
                print(f"  - No 'infos' data returned for {date_str}.")
                return None # No data for this day

            all_labels_units_day = set()
            for info_item in infos:
                label = info_item.get('label')
                unit = info_item.get('unit', '')
                records = info_item.get('records', [])
                if not label: continue

                header_name = f"{label}[{unit}]" if unit else label
                all_labels_units_day.add(header_name)

                for record in records:
                    record_time_str = record.get('time')
                    record_value_str = record.get('value')

                    datetime_key = parse_api_timestamp(target_date, record_time_str)

                    if datetime_key and record_value_str is not None:
                        formatted_val = format_value(record_value_str)
                        data_by_datetime[datetime_key][header_name] = formatted_val
                    # else: print(f"  - Skipping record, invalid time/value: {record}") # Debug noise

            if data_by_datetime:
                print(f"  + OK: Fetched {len(data_by_datetime)} timestamps for {date_str} with labels: {', '.join(sorted(list(all_labels_units_day)))}")
                return dict(data_by_datetime)
            else:
                 print(f"  - No valid records found for {date_str} despite API success.")
                 return None

        else:
            msg = data.get('msg', 'No data structure or unknown error')
            print(f"  - API Fail for {date_str}: {msg}")
            return None

    except requests.exceptions.HTTPError as e:
        print(f"  - HTTP error {e.response.status_code} fetching for {date_str}: {e.response.text}")
        if e.response.status_code == 401:
             print("  -> Authentication error. Stopping.")
             raise ConnectionAbortedError("Token expired or invalid") # Stop fetch
        elif e.response.status_code == 429:
             print("  -> Rate limited! Consider increasing REQUEST_DELAY value.")
        # Handle other specific errors as needed
        return None # Continue unless it was auth error
    except requests.exceptions.RequestException as e:
        print(f"  - Network/request error fetching for {date_str}: {e}")
        return None
    except json.JSONDecodeError:
        print(f"  - Error decoding JSON for {date_str}. Raw response:")
        print("  ", response.text[:200] + ('...' if len(response.text) > 200 else '')) # Print snippet
        return None


# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(
        description="Extract historical data from Sunsynk API (limited to last 90 days by API).",
        epilog="If no dates are provided, fetches today's data. "
               "If one date (YYYY-MM-DD) is provided, fetches from yesterday back to that date."
    )
    # Remove user/pass arguments
    # parser.add_argument("username", help="Your Sunsynk portal username (email).")
    # parser.add_argument("password", help="Your Sunsynk portal password.")
    parser.add_argument("dates", nargs='*', help="Date(s) in YYYY-MM-DD format. "
                                                "Either one date (start) or two dates (start end).")
    parser.add_argument("-o", "--outputdir", default=".",
                        help="Output directory for the CSV file (default: current directory)")
    args = parser.parse_args()

    username, password, cred_source = get_credentials()
    if not (username and password):
        print("Exiting.")
        return

    start_dt_in = None
    end_dt_in = None
    export_mode = "" # For filename

    try:
        if len(args.dates) == 0:
            # Mode 1: Today
            start_dt = date.today()
            end_dt = date.today()
            export_mode = "today"
            print(f"\nNo dates provided. Fetching data for today: {start_dt.strftime('%Y-%m-%d')}")
        elif len(args.dates) == 1:
            # Mode 2: Yesterday back to single date
            start_dt = datetime.strptime(args.dates[0], "%Y-%m-%d").date()
            end_dt = date.today() - timedelta(days=1)
            export_mode = "range"
            print(f"\nOne date provided. Fetching data from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} (yesterday)")
        elif len(args.dates) == 2:
            # Mode 3: Specific range
            start_dt = datetime.strptime(args.dates[0], "%Y-%m-%d").date()
            end_dt = datetime.strptime(args.dates[1], "%Y-%m-%d").date()
            export_mode = "range"
            print(f"\nTwo dates provided. Fetching data from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
        else:
            print("Error: Invalid number of date arguments. Provide zero, one (start), or two (start end).")
            return

        # Ensure start <= end after defaults
        if start_dt > end_dt:
            print(f"Warning: Start date ({start_dt}) is after end date ({end_dt}). Swapping them.")
            start_dt, end_dt = end_dt, start_dt # Swap them

        # Keep track of the requested/effective range for filename
        effective_start_str = start_dt.strftime("%Y-%m-%d")
        effective_end_str = end_dt.strftime("%Y-%m-%d")


    except ValueError:
        print("Error: Invalid date format in arguments. Please use YYYY-MM-DD.")
        return


    # 90-day check
    today_date = date.today()
    ninety_days_ago = today_date - timedelta(days=90)
    if start_dt < ninety_days_ago:
        print(f"\nWarning: Start date {start_dt.strftime('%Y-%m-%d')} is older than 90 days ({ninety_days_ago.strftime('%Y-%m-%d')}).")
        print("         API data older than 90 days is usually unavailable.")
        # Confirmation could be added here if desired


    # --- Start API Interaction ---
    access_token = login(username, password)
    if not access_token:
        print("Exiting due to login failure.")
        return

    plants = get_plants(access_token)
    if not plants:
        print("Exiting: Could not retrieve plant list.")
        return

    # --- Select Plant ---
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

    if not target_plant_id: # Should not happen if selection works, but safety check
         print("Error: Plant ID could not be determined.")
         return


    # --- Fetch Data Loop ---
    all_data_by_datetime = {} # Master dict {datetime_object: {label_unit: value}}
    all_headers = set()   # Collect all unique headers
    stop_fetching = False
    print(f"\nStarting data fetch loop from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}...")

    current_loop_date = start_dt
    while current_loop_date <= end_dt and not stop_fetching:
        try:
            daily_data_dict = get_daily_energy_data_restructured(access_token, target_plant_id, current_loop_date)
            if daily_data_dict:
                all_data_by_datetime.update(daily_data_dict)
                # Update header set
                for timestamp_data in daily_data_dict.values():
                     all_headers.update(timestamp_data.keys())

        except ConnectionAbortedError: # Raised on 401 error
             print("Stopping data fetch loop due to authentication error.")
             stop_fetching = True
             all_data_by_datetime = {} # Clear potentially incomplete data
             break # Exit the loop

        current_loop_date += timedelta(days=1)


    # --- Write data to CSV ---
    if not all_data_by_datetime:
        print("\nNo data was successfully collected or fetch aborted. CSV file will not be created.")
        return

    # Prepare headers
    if not all_headers:
         print("\nNo data labels/headers found in collected records. Cannot create CSV.")
         return

    sorted_unique_headers = sorted(list(all_headers))
    final_fieldnames = ["DateTime"] + sorted_unique_headers # Ensure DateTime is first

    # Create dynamic output filename based on EFFECTIVE dates
    if export_mode == "today":
         output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}_today.csv"
    elif start_dt == end_dt: # Handles single date query that results in one day
         output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}.csv"
    else:
         output_filename = f"sunsynk_plant_{target_plant_id}_{effective_start_str}_to_{effective_end_str}.csv"

    output_path = os.path.join(args.outputdir, output_filename)

    print(f"\nData collection loop finished. Writing {len(all_data_by_datetime)} timestamp records to {output_path}...")

    # Create output directory if it doesn't exist
    try:
        os.makedirs(args.outputdir, exist_ok=True)
    except OSError as e:
        print(f"Error creating output directory '{args.outputdir}': {e}")
        return

    try:
        # Sort data by datetime keys before writing
        sorted_datetimes = sorted(all_data_by_datetime.keys())

        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=final_fieldnames)
            writer.writeheader()

            for dt_key in sorted_datetimes:
                timestamp_data = all_data_by_datetime[dt_key]
                row_to_write = {"DateTime": dt_key.strftime("%Y-%m-%d %H:%M:%S")} # Format datetime key for CSV
                row_to_write.update(timestamp_data) # Add the label[unit]:value pairs
                writer.writerow(row_to_write) # DictWriter handles missing headers

        print(f"Data successfully written to {output_path}")

    except IOError as e:
        print(f"Error writing CSV file '{output_path}': {e}")
    except KeyError as e:
         print(f"CSV writing error: Missing key {e}.")

if __name__ == "__main__":
    main()