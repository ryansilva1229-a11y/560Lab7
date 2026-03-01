# imports
import requests
import smtplib
import time
import math
import os
import kagglehub
import pandas as pd
from datetime import datetime
from email.mime.text import MIMEText

# thingsboard connection configuration
tb_url = "http://18.117.119.232:8080"
username = "tenant@thingsboard.org"
password = "tenant"

# list of our devices and their device ids
devices = {
    "Elise's Phone": "044e1400-1424-11f1-afbc-b9fd8223c0fd",
    "Ryan's Phone": "98aeda80-14dd-11f1-bbd8-d1b3eca879f5",
    "Jordan's Phone": "670c8f40-1433-11f1-afbc-b9fd8223c0fd",
}

# for sending email alerts
smtp_server = "smtp.gmail.com"
smtp_port = 587
# gmail account sender (our alert email for this lab)
gmail_sender = "childsafetyalerts1@gmail.com"
gmail_app_password = "qovzibsilzprjjwj"
# email receiver (PARENT'S EMAIL)
email_receiver = "hadidi@usc.edu"

# defining safe zones
safe_zones = [
    # home
    (34.028051, -118.288487, 200, "Home"),
    # school
    (34.020000, -118.290000, 300, "School"),
]

# state tracking for alerts
alerted = {}
last_positions = {}
last_seen = {}
zone_states = {}

# restaurant data for food alert
path = kagglehub.dataset_download("thedevastator/fast-food-restaurants-in-the-united-states")
csv_file = [f for f in os.listdir(path) if f.endswith(".csv")][0]
restaurant_df = pd.read_csv(os.path.join(path, csv_file))

# getting the latest telemetry for a certain device
def get_telemetry(auth_token, device_id):
    url = f"{tb_url}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries"
    headers = {"X-Authorization": f"Bearer {auth_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return {k: v[0]["value"] for k, v in response.json().items()}

# sending email alerts
def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_sender
    msg["To"] = email_receiver
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(gmail_sender, gmail_app_password)
        server.sendmail(gmail_sender, email_receiver, msg.as_string())
    print(f"Email sent: {subject}")

# function to alert only once per event
def alert_once(key, subject, body):
    if key not in alerted:
        send_email(subject, body)
        alerted[key] = True

# resetting alert state when condition clears
def reset_alert(key):
    alerted.pop(key, None)


# low battery alert
def check_low_battery(device_name, data):
    batt = int(float(data.get("batt", 100)))
    key = f"{device_name}:low_battery"
    if batt < 20:
        alert_once(key, f"Low Battery: {device_name}", f"{device_name} battery is at {batt}%. Please charge soon.")
    else:
        reset_alert(key)

# leaving home with low battery alert
def check_leaving_home_low_battery(device_name, data):
    batt = int(float(data.get("batt", 100)))
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    key = f"{device_name}:leaving_home_low_batt"
    home_lat,home_lon,home_radius,_ = safe_zones[0]
    r = 6371000
    phi1,phi2 = math.radians(lat), math.radians(home_lat)
    a = math.sin(math.radians(home_lat-lat)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(home_lon-lon)/2)**2
    dist = r*2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    if dist > home_radius and batt < 50:
        alert_once(key, f"Left Home with Low Battery: {device_name}", f"{device_name} has left home with only {batt}% battery.")
    else:
        reset_alert(key)


# safe zone alert
def check_safe_zones(device_name, data):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    for zone in safe_zones:
        zone_lat,zone_lon,radius,zone_name = zone
        key = f"{device_name}:{zone_name}"
        r = 6371000
        phi1,phi2 = math.radians(lat), math.radians(zone_lat)
        a = math.sin(math.radians(zone_lat-lat)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(zone_lon-lon)/2)**2
        dist = r*2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        currently_inside = dist <= radius
        was_inside = zone_states.get(key)
        if was_inside is None:
            zone_states[key] = currently_inside
        elif currently_inside and not was_inside:
            send_email(f"Entered {zone_name}: {device_name}", f"{device_name} has entered {zone_name}.")
            zone_states[key] = True
        elif not currently_inside and was_inside:
            send_email(f"Left {zone_name}: {device_name}", f"{device_name} has left {zone_name}.")
            zone_states[key] = False

# curfew alert
def check_curfew(device_name, data):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    key = f"{device_name}:curfew"
    in_any_zone = False
    for zone in safe_zones:
        zone_lat,zone_lon,radius,_ = zone
        r = 6371000
        phi1,phi2 = math.radians(lat), math.radians(zone_lat)
        a = math.sin(math.radians(zone_lat-lat)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(zone_lon-lon)/2)**2
        dist = r*2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        if dist <= radius:
            in_any_zone = True
    if datetime.now().hour >= 21 and not in_any_zone:
        alert_once(key, f"Curfew Alert: {device_name}", f"{device_name} is outside a safe zone after 21:00.")
    else:
        reset_alert(key)


# speed alert
def check_speed(device_name, data):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    tst = int(float(data.get("tst", 0)))
    key = f"{device_name}:speed"
    if device_name in last_positions:
        prev_lat,prev_lon,prev_tst = last_positions[device_name]
        time_diff = tst-prev_tst
        if time_diff > 0:
            r = 6371000
            phi1,phi2 = math.radians(lat), math.radians(prev_lat)
            a = math.sin(math.radians(prev_lat-lat)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(prev_lon-lon)/2)**2
            dist = r*2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            speed_kmh = (dist/time_diff) * 3.6
            if speed_kmh > 60:
                alert_once(key, f"Speed Alert: {device_name}", f"{device_name} is moving at {speed_kmh:.1f} km/h.")
            else:
                reset_alert(key)
    last_positions[device_name] = (lat, lon, tst)

# connection alert
def check_connection(device_name, data):
    tst = int(float(data.get("tst", 0)))
    key = f"{device_name}:offline"
    last_seen[device_name] = max(last_seen.get(device_name, 0), tst)
    time_since_seen = time.time()-last_seen[device_name]
    if time_since_seen > 300:
        alert_once(key, f"Device Offline: {device_name}", f"{device_name} has been offline for {int(time_since_seen//60)} minutes.")
    else:
        reset_alert(key)


# friend nearby alert
def check_friend_nearby(auth_token):
    device_list = []
    for device_name, device_id in devices.items():
        data = get_telemetry(auth_token, device_id)
        if data is None:
            continue
        device_list.append((device_name, float(data.get("lat", 0)), float(data.get("lon", 0))))
    for device in device_list:
        for other in device_list:
            if device[0] == other[0]:
                continue
            r = 6371000
            phi1,phi2 = math.radians(device[1]), math.radians(other[1])
            a = math.sin(math.radians(other[1]-device[1])/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(other[2]-device[2])/2)**2
            dist = r*2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            pair_key = ":".join(sorted([device[0], other[0]])) + ":friend_nearby"
            if dist <= 1750:
                alert_once(pair_key, f"Friend Nearby: {device[0]} & {other[0]}",
                        f"{device[0]} and {other[0]} are {dist:.0f} meters away from each other.")
            else:
                reset_alert(pair_key)

# food nearby alert
def check_food_nearby(device_name, data):
    lat = float(data.get("lat", 0))
    lon = float(data.get("lon", 0))
    lat_min = lat-(1/110)
    lat_max = lat+(1/110)
    lon_min = lon-(1/(math.cos(math.radians(lat))*111))
    lon_max = lon+(1/(math.cos(math.radians(lat))*111))
    suggestions = [
        row["name"] for _, row in restaurant_df.iterrows()
        if lat_min <= row["latitude"] <= lat_max and lon_min <= row["longitude"] <= lon_max
    ]
    key = f"{device_name}:food_nearby"
    if len(suggestions) > 0:
        alert_once(key, f"Food Nearby: {device_name}", f"Fast food restaurants near {device_name}:\n" + "\n".join(suggestions))


if __name__ == "__main__":
    while True:
        auth_token = requests.post(f"{tb_url}/api/auth/login", json={"username": username, "password": password}).json()["token"]
        for device_name, device_id in devices.items():
            print(f"\n{device_name}:")
            data = get_telemetry(auth_token, device_id)
            check_low_battery(device_name, data)
            check_leaving_home_low_battery(device_name, data)
            check_safe_zones(device_name, data)
            check_curfew(device_name, data)
            check_speed(device_name, data)
            check_connection(device_name, data)
            check_food_nearby(device_name, data)

        print("\nChecking for nearby friends...")
        check_friend_nearby(auth_token)
        # checking every minute
        time.sleep(60)