import configparser
import csv
import os
import sys
import json
import websocket
import requests
from datetime import datetime, timezone

# Read configuration
config = configparser.ConfigParser()
config.read('config.ini')

# Home Assistant settings
HA_URL = config['homeassistant']['url'].rstrip('/')
HA_TOKEN = config['homeassistant']['token']
SENSOR_NAME = config['homeassistant']['sensor_name']

# File settings
DATA_FILE = config['files']['data_file']
UPLOAD_CHECKPOINT_FILE = config['files']['upload_checkpoint_file']

# Convert HTTP URL to WebSocket URL
WS_URL = HA_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'

msg_id = 1

def read_data_from_csv():
    """Read all data from CSV file and return as list of (timestamp, value) tuples."""
    data = []

    if not os.path.exists(DATA_FILE):
        print(f"Error: {DATA_FILE} not found. Run scrape.py first.")
        sys.exit(1)

    with open(DATA_FILE, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header

        for row in reader:
            if len(row) == 2:
                timestamp = int(row[0])
                value = float(row[1])
                data.append((timestamp, value))

    # Sort by timestamp to ensure chronological order
    data.sort(key=lambda x: x[0])
    return data

def get_last_uploaded_timestamp():
    """Get the last uploaded timestamp from checkpoint file."""
    try:
        if os.path.exists(UPLOAD_CHECKPOINT_FILE):
            with open(UPLOAD_CHECKPOINT_FILE, 'r') as f:
                return int(f.read().strip())
    except:
        pass
    return None

def save_upload_checkpoint(timestamp):
    """Save the last uploaded timestamp."""
    with open(UPLOAD_CHECKPOINT_FILE, 'w') as f:
        f.write(str(timestamp))

def send_ws_message(ws, msg_type, **kwargs):
    """Send a WebSocket message and get response."""
    global msg_id
    message = {"id": msg_id, "type": msg_type, **kwargs}
    msg_id += 1
    ws.send(json.dumps(message))
    result = ws.recv()
    return json.loads(result)

def import_statistics_batch(ws, statistics):
    """Import a batch of statistics via WebSocket."""
    global msg_id

    import_msg = {
        "id": msg_id,
        "type": "recorder/import_statistics",
        "metadata": {
            "has_mean": False,
            "has_sum": True,
            "name": "CARMA Energy Daily",
            "source": "recorder",
            "statistic_id": SENSOR_NAME,
            "unit_of_measurement": "kWh"
        },
        "stats": statistics
    }
    msg_id += 1

    ws.send(json.dumps(import_msg))
    result = ws.recv()
    response = json.loads(result)

    return response.get("success", False)

def upload():
    """Main upload function using WebSocket API."""

    # Validate token
    if HA_TOKEN == "YOUR_LONG_LIVED_ACCESS_TOKEN_HERE":
        print("Error: Please update the Home Assistant token in config.ini")
        print("Get it from: Profile -> Security -> Create Long-Lived Access Token")
        sys.exit(1)

    # Read all data from CSV
    print("Reading data from CSV...")
    data = read_data_from_csv()

    if not data:
        print("No data found in CSV file")
        return

    print(f"Found {len(data)} data points in CSV")

    # Get last uploaded checkpoint
    last_uploaded = get_last_uploaded_timestamp()

    # Filter for new data only
    if last_uploaded:
        new_data = [(ts, val) for ts, val in data if ts > last_uploaded]
        print(f"Last upload was at {datetime.fromtimestamp(last_uploaded)}")
        print(f"Found {len(new_data)} new data points to upload")
    else:
        new_data = data
        print("No previous upload found - this is initial upload")
        print(f"Will upload all {len(new_data)} data points")

    if not new_data:
        print("No new data to upload")
        return

    # Convert daily values to cumulative for total_increasing sensor
    print("Converting to cumulative values...")

    # Get the starting cumulative value (if we had previous uploads)
    if last_uploaded:
        # Find cumulative sum up to last uploaded timestamp
        previous_data = [(ts, val) for ts, val in data if ts <= last_uploaded]
        starting_cumulative = sum(val for _, val in previous_data)
    else:
        starting_cumulative = 0

    # Calculate cumulative values for new data
    cumulative_new_data = []
    cumulative_sum = starting_cumulative

    for timestamp, value in new_data:
        cumulative_sum += value
        cumulative_new_data.append((timestamp, cumulative_sum))

    # Prepare statistics for import
    statistics = []
    for timestamp, cumulative_value in cumulative_new_data:
        # Add 23 hours (82800 seconds) to move from midnight to 11 PM of same day
        # Home Assistant requires timestamps at top of the hour (minutes and seconds = 0)
        end_of_day_timestamp = timestamp + 82800  # 23:00:00 of the same day
        dt = datetime.fromtimestamp(end_of_day_timestamp, tz=timezone.utc)
        stat_entry = {
            "start": dt.isoformat(),
            "state": cumulative_value,
            "sum": cumulative_value
        }
        statistics.append(stat_entry)

    print(f"\nConnecting to Home Assistant via WebSocket...")
    print(f"Date range: {datetime.fromtimestamp(new_data[0][0])} to {datetime.fromtimestamp(new_data[-1][0])}")

    try:
        # Connect to WebSocket
        ws = websocket.create_connection(WS_URL)

        # Receive auth required message
        auth_msg = ws.recv()

        # Send auth token
        auth_data = {"type": "auth", "access_token": HA_TOKEN}
        ws.send(json.dumps(auth_data))
        auth_result = ws.recv()

        auth_response = json.loads(auth_result)
        if auth_response.get("type") != "auth_ok":
            print("✗ Authentication failed!")
            ws.close()
            sys.exit(1)

        print("✓ Connected and authenticated")

        # Create the sensor entity first (required before importing statistics)
        print("\nCreating sensor entity...")
        try:
            sensor_payload = {
                "state": "0",
                "attributes": {
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "friendly_name": "CARMA Energy Daily"
                }
            }
            headers = {
                'Authorization': f'Bearer {HA_TOKEN}',
                'Content-Type': 'application/json'
            }
            response = requests.post(
                f"{HA_URL}/api/states/{SENSOR_NAME}",
                headers=headers,
                json=sensor_payload,
                timeout=10
            )
            if response.status_code in [200, 201]:
                print("✓ Sensor entity created")
            else:
                print(f"Note: Sensor creation returned {response.status_code} (may already exist)")
        except Exception as e:
            print(f"Warning: Could not create sensor: {e}")

        # Import statistics in batches to avoid overwhelming the system
        batch_size = 100
        total_batches = (len(statistics) + batch_size - 1) // batch_size

        print(f"\nImporting {len(statistics)} data points in {total_batches} batch(es)...")

        for i in range(0, len(statistics), batch_size):
            batch = statistics[i:i+batch_size]
            batch_num = i // batch_size + 1

            success = import_statistics_batch(ws, batch)

            if success:
                print(f"✓ Batch {batch_num}/{total_batches} imported ({len(batch)} points)")
                # Save checkpoint after each successful batch
                last_timestamp = cumulative_new_data[min(i+batch_size, len(cumulative_new_data))-1][0]
                save_upload_checkpoint(last_timestamp)
            else:
                print(f"✗ Batch {batch_num}/{total_batches} failed")
                ws.close()
                sys.exit(1)

        ws.close()

        # Get final values
        final_timestamp, final_value = cumulative_new_data[-1]

        print(f"\n{'='*60}")
        print(f"✓ Upload complete!")
        print(f"✓ Imported {len(statistics)} data points")
        print(f"✓ Final cumulative value: {final_value:.2f} kWh")
        print(f"✓ Checkpoint saved at {datetime.fromtimestamp(final_timestamp)}")
        print(f"\nYou can now view your energy statistics in Home Assistant:")
        print(f"  - Entity: {SENSOR_NAME}")
        print(f"  - URL: {HA_URL}/config/entities")
        print(f"  - Energy Dashboard: {HA_URL}/energy")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    upload()
