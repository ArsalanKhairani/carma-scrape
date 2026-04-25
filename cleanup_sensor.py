import configparser
import json
import websocket
import requests
import os

# Read configuration
config = configparser.ConfigParser()
config.read('config.ini')

HA_URL = config['homeassistant']['url'].rstrip('/')
HA_TOKEN = config['homeassistant']['token']
SENSOR_NAME = config['homeassistant']['sensor_name']
UPLOAD_CHECKPOINT_FILE = config['files']['upload_checkpoint_file']

HEADERS = {
    'Authorization': f'Bearer {HA_TOKEN}',
    'Content-Type': 'application/json'
}

WS_URL = HA_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/websocket'

print(f"Cleaning up sensor: {SENSOR_NAME}")
print("=" * 60)

# Step 1: Delete the sensor entity
print("\n1. Deleting sensor entity...")
try:
    response = requests.delete(
        f"{HA_URL}/api/states/{SENSOR_NAME}",
        headers=HEADERS,
        timeout=10
    )
    if response.status_code in [200, 201]:
        print(f"   ✓ Sensor entity deleted")
    else:
        print(f"   Note: {response.status_code} - {response.text[:100]}")
except Exception as e:
    print(f"   Error: {e}")

# Step 2: Clear statistics via WebSocket
print("\n2. Clearing statistics from database...")
try:
    ws = websocket.create_connection(WS_URL)

    # Auth
    auth_msg = ws.recv()
    auth_data = {"type": "auth", "access_token": HA_TOKEN}
    ws.send(json.dumps(auth_data))
    auth_result = ws.recv()

    auth_response = json.loads(auth_result)
    if auth_response.get("type") != "auth_ok":
        print("   ✗ Authentication failed!")
        ws.close()
    else:
        print("   ✓ Connected to WebSocket")

        # Clear statistics metadata
        clear_msg = {
            "id": 1,
            "type": "recorder/clear_statistics",
            "statistic_ids": [SENSOR_NAME]
        }
        ws.send(json.dumps(clear_msg))
        result = ws.recv()
        response = json.loads(result)

        if response.get("success"):
            print(f"   ✓ Statistics cleared for {SENSOR_NAME}")
        else:
            print(f"   Note: {response}")

        ws.close()

except Exception as e:
    print(f"   Error: {e}")

# Step 3: Delete checkpoint file
print("\n3. Deleting checkpoint file...")
try:
    if os.path.exists(UPLOAD_CHECKPOINT_FILE):
        os.remove(UPLOAD_CHECKPOINT_FILE)
        print(f"   ✓ Deleted {UPLOAD_CHECKPOINT_FILE}")
    else:
        print(f"   Note: Checkpoint file doesn't exist")
except Exception as e:
    print(f"   Error: {e}")

# Step 4: Call recorder.purge to clean up old data
print("\n4. Purging old recorder data...")
try:
    response = requests.post(
        f"{HA_URL}/api/services/recorder/purge_entities",
        headers=HEADERS,
        json={
            "entity_id": SENSOR_NAME,
        },
        timeout=30
    )
    if response.status_code in [200, 201]:
        print(f"   ✓ Purge initiated (this may take a moment)")
    else:
        print(f"   Note: {response.status_code} - {response.text[:100]}")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "=" * 60)
print("Cleanup complete!")
print("\nYou can now run upload_websocket.py to re-import with clean data.")
