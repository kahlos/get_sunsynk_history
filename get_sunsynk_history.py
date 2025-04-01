import requests
import json
import argparse
from datetime import datetime, timedelta
import csv
import time # To add delays

# Configuration
# Using the base URL commonly found in the provided client libraries
BASE_URL = "https://pv.inteless.com"
LOGIN_URL = f"{BASE_URL}/oauth/token"
PLANTS_URL = f"{BASE_URL}/api/v1/plants"
DAILY_ENERGY_URL_TEMPLATE = f"{BASE_URL}/api/v1/plant/energy/{{plant_id}}/day"
CLIENT_ID = "csp-web" # From login examples/libraries

# --- Helper Functions ---

def login(username, password):
    """Authenticates with the API and returns the access token."""
    print("Attempting to log in...")
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
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        data = response.json()

        if data.get("success"):
            access_token = data.get("data", {}).get("access_token")
            if access_token:
                print("Login successful.")
                return access_token
            else:
                print("Login failed: Access token not found in response.")
                return None
        else:
            print(f"Login failed: {data.get('msg', 'Unknown error')}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Login error: {e}")
        return None
    except json.JSONDecodeError:
        print("Login error: Could not decode JSON response.")
        print("Raw response:", response.text)
        return None

def get_plants(access_token):
    """Fetches plant information."""
    print("Fetching plant information...")
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
             # Assuming the first plant is the target for now
             # In a multi-plant setup, you might want to add selection logic
             return plants
        else:
            print(f"Failed to get plants: {data.get('msg', 'Unknown error')}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching plants: {e}")
        return None
    except json.JSONDecodeError:
        print("Error fetching plants: Could not decode JSON response.")
        print("Raw response:", response.text)
        return None

def get_daily_energy_data(access_token, plant_id, target_date):
    """Fetches energy data for a specific plant and date."""
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"Fetching data for plant {plant_id} on {date_str}...")
    url = DAILY_ENERGY_URL_TEMPLATE.format(plant_id=plant_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    params = {
        "date": date_str,
        "id": plant_id,
        "lan": "en" # As seen in node client
    }
    try:
        # Add a small delay to avoid overwhelming the API
        time.sleep(0.5) # Sleep for 500 milliseconds

        response = requests.get(url, headers=headers, params=params, timeout=30) # Increased timeout for potentially larger data
        response.raise_for_status()
        data = response.json()

        if data.get("success") and "data" in data and "infos" in data["data"]:
            return data["data"]["infos"]
        else:
            print(f"Failed to get energy data for {date_str}: {data.get('msg', 'No data returned or unknown error')}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching energy data for {date_str}: {e}")
        # Check for specific status codes if helpful (e.g., 429 Too Many Requests)
        if response.status_code == 401:
            print("Authentication error (token might have expired).")
        elif response.status_code == 404:
            print(f"Endpoint not found for {date_str}. Maybe no data?")
        elif response.status_code == 500:
             print(f"Server error for {date_str}.")
        return None
    except json.JSONDecodeError:
        print(f"Error decoding energy data JSON for {date_str}.")
        print("Raw response:", response.text)
        return None


# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(description="Extract historical data from Sunsynk API.")
    parser.add_argument("username", help="Your Sunsynk portal username (email).")
    parser.add_argument("password", help="Your Sunsynk portal password.")
    parser.add_argument("start_date", help="Start date in YYYY-MM-DD format.")
    parser.add_argument("end_date", help="End date in YYYY-MM-DD format.")
    parser.add_argument("-o", "--output", default="sunsynk_historical_data.csv",
                        help="Output CSV file name (default: sunsynk_historical_data.csv)")
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

    access_token = login(args.username, args.password)
    if not access_token:
        return # Login failed

    plants = get_plants(access_token)
    if not plants:
        return # Failed to get plants

    # --- Assuming the first plant is the target ---
    # You could add logic here to list plants and ask the user to choose
    target_plant_id = plants[0]['id']
    target_plant_name = plants[0]['name']
    print(f"Using Plant ID: {target_plant_id} (Name: {target_plant_name})")
    # -------------------------------------------

    all_data = []
    current_date = start_dt
    while current_date <= end_dt:
        daily_data = get_daily_energy_data(access_token, target_plant_id, current_date)
        if daily_data:
            # The response nests data: { infos: [ {label, unit, records: [{time, value}, ...]}, ...] }
            # Flatten this for the CSV
            for info_item in daily_data:
                label = info_item.get('label')
                unit = info_item.get('unit')
                records = info_item.get('records', [])
                for record in records:
                    # Note: The 'time' field within daily records often seems to be just the date again,
                    # or a fixed time like 00:00:00. The primary granularity here is the day.
                    # We'll use the date we requested for clarity.
                    record_time_str = record.get('time', '') # Original time from record
                    record_value = record.get('value')

                    all_data.append({
                        "Date": current_date.strftime("%Y-%m-%d"),
                        "Label": label,
                        "Unit": unit,
                        # "RecordTime": record_time_str, # Optional: include the time string from the record itself
                        "Value": record_value
                    })

        # Move to the next day
        current_date += timedelta(days=1)

    # Write data to CSV
    if not all_data:
        print("No data collected. CSV file will not be created.")
        return

    print(f"Writing data to {args.output}...")
    try:
        with open(args.output, 'w', newline='', encoding='utf-8') as csvfile:
            # Define header order
            fieldnames = ['Date', 'Label', 'Value', 'Unit'] # Ordered header
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for row in all_data:
                 # Ensure only fields defined in fieldnames are written
                filtered_row = {k: row[k] for k in fieldnames if k in row}
                writer.writerow(filtered_row)
        print("Data successfully written to CSV.")
    except IOError as e:
        print(f"Error writing CSV file: {e}")
    except KeyError as e:
         print(f"CSV writing error: Missing expected key {e}. Data might be incomplete.")


if __name__ == "__main__":
    main()