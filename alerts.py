# imports
import requests
import time
import math
import os
import kagglehub
import pandas as pd
from datetime import datetime

# thingsboard connection configuration
TB_URL = "http://18.117.119.232:8080"
USERNAME = "tenant@thingsboard.org"
PASSWORD = "tenant"

# list of our devices and their device ids
devices = {
    "Elise's Phone":  "044e1400-1424-11f1-afbc-b9fd8223c0fd",
    "Ryan's Phone":   "98aeda80-14dd-11f1-bbd8-d1b3eca879f5",
    "Jordan's Phone": "670c8f40-1433-11f1-afbc-b9fd8223c0fd",
}

# defining safe zones: (lat, lon, radius_meters, name)
safe_zones = [
    (34.028051, -118.288487, 200, "Home"),
    (34.020000, -118.290000, 300, "School"),
]

alerted = {}
last_positions = {} 
last_seen = {}
zone_states = {} 

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def make_key(device_id: str, tag: str) -> str:
    return f"{device_id}:{tag}"


def alert_once(device_id: str, tag: str, alert_type: str, message: str, auth_token: str):
    key = make_key(device_id, tag)
    if key not in alerted:
        send_alert_to_device(auth_token, device_id, alert_type, message)
        alerted[key] = True


def reset_alert(device_id: str, tag: str):
    key = make_key(device_id, tag)
    alerted.pop(key, None)


def get_auth_token() -> str:
    resp = requests.post(
        f"{TB_URL}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def get_telemetry(auth_token: str, device_id: str) -> dict:
    url = f"{TB_URL}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries"
    headers = {"X-Authorization": f"Bearer {auth_token}"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return {k: v[0]["value"] for k, v in resp.json().items()}


def send_alert_to_device(auth_token: str, device_id: str, alert_type: str, message: str):
    url = f"{TB_URL}/api/plugins/telemetry/DEVICE/{device_id}/timeseries/ANY"
    headers = {"X-Authorization": f"Bearer {auth_token}"}
    payload = {
        "ts": int(time.time() * 1000),
        "values": {alert_type: message}
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    if resp.status_code in (200, 201):
        print(f"  [ALERT] {device_id} | {alert_type}: {message}")
    else:
        print(f"  [ALERT FAILED] {device_id} | {resp.status_code}: {resp.text}")

def check_low_battery(device_id: str, data: dict, auth_token: str):
    batt = int(float(data.get("batt", 100)))
    tag = "low_battery"
    if batt < 20:
        alert_once(device_id, tag, tag, f"Battery at {batt}%", auth_token)
    else:
        reset_alert(device_id, tag)


def check_leaving_home_low_battery(device_id: str, data: dict, auth_token: str):
    batt = int(float(data.get("batt", 100)))
    lat  = float(data.get("lat", 0))
    lon  = float(data.get("lon", 0))
    home_lat, home_lon, home_radius, _ = safe_zones[0]
    tag  = "leaving_home_low_batt"
    dist = haversine(lat, lon, home_lat, home_lon)
    if dist > home_radius and batt < 50:
        alert_once(device_id, tag, tag, f"Left home with {batt}% battery", auth_token)
    else:
        reset_alert(device_id, tag)


def check_safe_zones(device_name: str, device_id: str, data: dict, auth_token: str):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    for zone_lat, zone_lon, radius, zone_name in safe_zones:
        state_key = f"{device_name}:{zone_name}"
        dist = haversine(lat, lon, zone_lat, zone_lon)
        currently_inside = dist <= radius
        was_inside = zone_states.get(state_key)

        if was_inside is None:
            zone_states[state_key] = currently_inside
        elif currently_inside and not was_inside:
            alert_once(device_id, zone_name, zone_name, f"Entered {zone_name} zone", auth_token)
            zone_states[state_key] = True
        elif not currently_inside and was_inside:
            alert_once(device_id, zone_name, zone_name, f"Left {zone_name} zone", auth_token)
            zone_states[state_key] = False


def check_curfew(device_name: str, device_id: str, data: dict, auth_token: str):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    tag = "curfew"
    in_any_zone = any(
        haversine(lat, lon, zl, zlo) <= r
        for zl, zlo, r, _ in safe_zones
    )
    if datetime.now().hour >= 21 and not in_any_zone:
        alert_once(device_id, tag, tag, f"{device_name} is outside a safe zone after 21:00.", auth_token)
    else:
        reset_alert(device_id, tag)


def check_speed(device_name: str, device_id: str, data: dict, auth_token: str):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    tst = int(float(data.get("tst", 0)))
    tag = "speed"
    if device_name in last_positions:
        prev_lat, prev_lon, prev_tst = last_positions[device_name]
        time_diff = tst - prev_tst
        if time_diff > 0:
            dist = haversine(lat, lon, prev_lat, prev_lon)
            speed_kmh = (dist / time_diff) * 3.6
            if speed_kmh > 60:
                alert_once(device_id, tag, tag, f"{device_name} is moving at {speed_kmh:.1f} km/h.", auth_token)
            else:
                reset_alert(device_id, tag)
    last_positions[device_name] = (lat, lon, tst)


def check_connection(device_name: str, device_id: str, data: dict, auth_token: str):
    tst = int(float(data.get("tst", 0)))
    tag = "offline"
    last_seen[device_name] = max(last_seen.get(device_name, 0), tst)
    time_since_seen = time.time() - last_seen[device_name]
    if time_since_seen > 300:
        alert_once(
            device_id, tag, tag,
            f"{device_name} has been offline for {int(time_since_seen // 60)} minutes.",
            auth_token,
        )
    else:
        reset_alert(device_id, tag)


def check_friend_nearby(auth_token: str, all_data: dict):
    positions = []
    for device_name, (device_id, data) in all_data.items():
        positions.append((device_name, device_id, float(data.get("lat", 0)), float(data.get("lon", 0))))

    seen_pairs = set()
    for i, (name_a, id_a, lat_a, lon_a) in enumerate(positions):
        for name_b, id_b, lat_b, lon_b in positions[i + 1:]:
            pair_tag = ":".join(sorted([name_a, name_b])) + ":friend_nearby"
            dist = haversine(lat_a, lon_a, lat_b, lon_b)
            if dist <= 1750:
                alert_once(id_a, pair_tag, "friend_nearby", f"{name_a} and {name_b} are {dist:.0f} m apart.", auth_token)
                alert_once(id_b, pair_tag, "friend_nearby", f"{name_a} and {name_b} are {dist:.0f} m apart.", auth_token)
            else:
                reset_alert(id_a, pair_tag)
                reset_alert(id_b, pair_tag)


def check_food_nearby(device_name: str, device_id: str, data: dict, auth_token: str, restaurant_df: pd.DataFrame):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    tag = "food_nearby"

    lat_min = lat - (1 / 110)
    lat_max = lat + (1 / 110)
    lon_delta = 1 / (math.cos(math.radians(lat)) * 111)
    lon_min = lon - lon_delta
    lon_max = lon + lon_delta

    nearby = restaurant_df[
        (restaurant_df["latitude"]  >= lat_min) & (restaurant_df["latitude"]  <= lat_max) &
        (restaurant_df["longitude"] >= lon_min) & (restaurant_df["longitude"] <= lon_max)
    ]["name"].tolist()

    if nearby:
        alert_once(
            device_id, tag, tag,
            f"Fast food restaurants near {device_name}:\n" + "\n".join(nearby),
            auth_token,
        )
    else:
        reset_alert(device_id, tag)


if __name__ == "__main__":
    # Load restaurant data once at startup
    print("Loading restaurant dataset...")
    path = kagglehub.dataset_download("thedevastator/fast-food-restaurants-in-the-united-states")
    csv_file = next(f for f in os.listdir(path) if f.endswith(".csv"))
    restaurant_df = pd.read_csv(os.path.join(path, csv_file))
    print(f"Loaded {len(restaurant_df)} restaurants.\n")

    while True:
        try:
            auth_token = get_auth_token()
        except Exception as e:
            print(f"[AUTH ERROR] {e}")
            time.sleep(60)
            continue

        all_data = {}
        for device_name, device_id in devices.items():
            print(f"\n--- {device_name} ---")
            try:
                data = get_telemetry(auth_token, device_id)
            except Exception as e:
                print(f"  [TELEMETRY ERROR] {e}")
                continue

            all_data[device_name] = (device_id, data)

            check_low_battery(device_id, data, auth_token)
            check_leaving_home_low_battery(device_id, data, auth_token)
            check_safe_zones(device_name, device_id, data, auth_token)
            check_curfew(device_name, device_id, data, auth_token)
            check_speed(device_name, device_id, data, auth_token)
            check_connection(device_name, device_id, data, auth_token)
            check_food_nearby(device_name, device_id, data, auth_token, restaurant_df)

        print("\n--- Checking for nearby friends ---")
        check_friend_nearby(auth_token, all_data)

        print("\nSleeping 60 s...\n")
        time.sleep(60)