import requests
import json
import argparse
from datetime import datetime, timedelta, date
import csv
import time
from collections import defaultdict
import os

# Configuration
BASE_URL = "https://api.sunsynk.net" # <--- Changed Base URL
LOGIN_URL = f"{BASE_URL}/oauth/token"
PLANTS_URL = f"{BASE_URL}/api/v1/plants"
DAILY_ENERGY_URL_TEMPLATE = f"{BASE_URL}/api/v1/plant/energy/{{plant_id}}/day"
CLIENT_ID = "csp-web"
REQUEST_DELAY = 0.6 # Seconds to wait between API calls to avoid rate limits

# --- Helper Functions ---

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
    if value_str is None:
        return ""
    try:
        # Use float for conversion robustness, check if it's a whole number
        num = float(value_str)
        if num.is_integer():
            return str(int(num))
        else:
            return value_str # Keep as original string if it has decimals
    except (ValueError, TypeError):
        # Handle non-numeric values if necessary, or just return original
        return value_str # Return original if it's not a valid number

def get_daily_energy_data(access_token, plant_id, target_date):
    """
    Fetches energy data for a specific plant and date, restructuring it.
    Returns a dict keyed by timestamp, value is {label[unit]: formatted_value}.
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
    data_by_time = defaultdict(dict) # Store {timestamp: {label_unit: value}}

    try:
        # Add delay
        time.sleep(REQUEST_DELAY)

        response = requests.get(url, headers=headers, params=params, timeout=45) # Increased timeout
        response.raise_for_status()
        data = response.json()

        if data.get("success") and "data" in data and "infos" in data["data"]:
            infos = data["data"]["infos"]
            if not infos:
                print(f"  - No 'infos' data returned for {date_str}.")
                return None # Return None if no data for the day

            all_headers_for_day = set() # Track headers found this day
            for info_item in infos:
                label = info_item.get('label')
                unit = info_item.get('unit', '') # Default to empty string if no unit
                records = info_item.get('records', [])
                if not label: continue # Skip if no label

                header_name = f"{label}[{unit}]" if unit else label # Create header like PV[W] or SOC[%]
                all_headers_for_day.add(header_name)

                if not records:
                    #print(f"  - No 'records' for label '{label}' on {date_str}.") # Becomes noisy
                    continue

                for record in records:
                    record_time_str = record.get('time')
                    record_value_str = record.get('value')

                    if record_time_str is None or record_value_str is None:
                        #print(f"  - Skipping record with missing time/value for label '{label}'") # Noisy
                        continue

                    formatted_val = format_value(record_value_str)
                    data_by_time[record_time_str][header_name] = formatted_val
            print(f"  + Fetched data with labels: {', '.join(sorted(list(all_headers_for_day)))}")
            return dict(data_by_time) # Convert back to regular dict
        else:
            msg = data.get('msg', 'No data structure or unknown error')
            print(f"  - Failed get_daily_energy_data for {date_str}: {msg}")
            if not data.get("success") and response.status_code == 200:
                print(f"  - API reported success=false for {date_str}. Raw response: {data}")
            return None

    except requests.exceptions.HTTPError as e:
        print(f"  - HTTP error fetching for {date_str} (Status {e.response.status_code}): {e.response.text}")
        if e.response.status_code == 401:
             print("  -> Authentication error. Stopping.")
             raise ConnectionAbortedError("Token expired or invalid") # Raise specific error to stop
        elif e.response.status_code == 429:
             print("  -> Rate limited (Too Many Requests). Consider increasing REQUEST_DELAY.")
        elif e.response.status_code == 500:
             print(f"  -> Server error (500) for {date_str}. Retrying might help later.")
        elif e.response.status_code == 404:
            print(f"  -> Data not found (404) for {date_str}. Likely no data available for this day.")

        return None # Continue to next day unless it was auth error
    except requests.exceptions.RequestException as e:
        print(f"  - Network/request error fetching for {date_str}: {e}")
        return None
    except json.JSONDecodeError:
        print(f"  - Error decoding energy data JSON for {date_str}.")
        print("  - Raw response:", response.text)
        return None

# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(description="Extract historical data from Sunsynk API (last 90 days).")
    parser.add_argument("username", help="Your Sunsynk portal username (email).")
    parser.add_argument("password", help="Your Sunsynk portal password.")
    parser.add_argument("start_date", help="Start date in YYYY-MM-DD format.")
    parser.add_argument("end_date", help="End date in YYYY-MM-DD format.")
    parser.add_argument("-o", "--outputdir", default=".",
                        help="Output directory for the CSV file (default: current directory)")
    args = parser.parse_args()

    try:
        start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        print("Error: Invalid date format. Please use YYYY-MM-DD.")
        return

    if start_dt > end_dt:
        print("Error: Start date cannot be after end date.")
        return

    # 90-day check
    today = date.today()
    ninety_days_ago = today - timedelta(days=90)
    if start_dt.date() < ninety_days_ago:
        print(f"Warning: Start date {args.start_date} is older than 90 days ({ninety_days_ago.strftime('%Y-%m-%d')}).")
        print("The API typically only stores data for the last 90 days. Older data may not be available.")
        # Optionally add confirmation here to proceed or exit
        # proceed = input("Continue anyway? (y/N): ").lower()
        # if proceed != 'y':
        #     return

    access_token = login(args.username, args.password)
    if not access_token:
        print("Exiting due to login failure.")
        return

    plants = get_plants(access_token)
    if not plants:
        print("Exiting because no plants were found or fetch failed.")
        return

    # --- Assuming the first plant ---
    if len(plants) > 1:
        print(f"Warning: Multiple plants found. Using the first one: ID={plants[0]['id']}, Name='{plants[0]['name']}'.")
        print("         Consider adding plant selection logic if this is not the desired plant.")
    target_plant_id = plants[0]['id']
    target_plant_name = plants[0]['name']
    print(f"Target Plant: ID={target_plant_id}, Name='{target_plant_name}'")
    # ------------------------------

    all_data_by_time = {} # Master dict {timestamp: {label_unit: value}}
    all_headers = set()   # Collect all unique headers encountered

    current_date = start_dt
    stop_fetching = False
    while current_date <= end_dt and not stop_fetching:
        try:
            daily_data_restructured = get_daily_energy_data(access_token, target_plant_id, current_date)
            if daily_data_restructured:
                 all_data_by_time.update(daily_data_restructured) # Merge day's data
                 # Update the set of all headers seen so far
                 for timestamp_data in daily_data_restructured.values():
                      all_headers.update(timestamp_data.keys())

            current_date += timedelta(days=1)

        except ConnectionAbortedError: # Raised on 401 error during data fetch
             print("Stopping data fetch due to authentication error.")
             stop_fetching = True
             all_data_by_time = {} # Clear data as it might be incomplete due to auth error
             break # Exit the loop

    # --- Write data to CSV ---
    if not all_data_by_time:
        print("\nNo data collected or fetch aborted. CSV file will not be created.")
        return

    # Prepare headers: DateTime first, then others sorted alphabetically
    if not all_headers:
         print("\nNo data labels found in collected records. Cannot create CSV.")
         return

    sorted_headers = sorted(list(all_headers))
    final_fieldnames = ["DateTime"] + sorted_headers

    # Create dynamic output filename
    output_filename = f"sunsynk_plant_{target_plant_id}_{args.start_date}_to_{args.end_date}.csv"
    output_path = os.path.join(args.outputdir, output_filename)

    print(f"\nData collection complete. Writing {len(all_data_by_time)} timestamp records to {output_path}...")

    # Create output directory if it doesn't exist
    try:
        os.makedirs(args.outputdir, exist_ok=True)
    except OSError as e:
        print(f"Error creating output directory '{args.outputdir}': {e}")
        return

    try:
        # Sort data by timestamp before writing
        sorted_timestamps = sorted(all_data_by_time.keys())

        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=final_fieldnames)
            writer.writeheader()

            for timestamp in sorted_timestamps:
                row_data = all_data_by_time[timestamp]
                row_to_write = {"DateTime": timestamp}
                row_to_write.update(row_data) # Add the label[unit]:value pairs
                # DictWriter handles missing keys automatically by writing empty strings
                writer.writerow(row_to_write)

        print(f"Data successfully written to {output_path}")

    except IOError as e:
        print(f"Error writing CSV file '{output_path}': {e}")
    except KeyError as e:
         print(f"CSV writing error: Missing expected key {e}. This shouldn't happen with DictWriter.")
         print(f"Problematic timestamp data: {all_data_by_time.get(timestamp, 'Not Found')}")

if __name__ == "__main__":
    main()