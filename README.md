# 560Lab7

**Team Members:** Elise Hadidi (1137648541), Jordan Davies (1857892197), Ryan Silva (6463166471) 
**Team Number:**  17

## Overview
This project is a child safety monitoring system that tracks mobile devices in real time using the ThingsBoard IoT platform and OwnTracks mobile app. It monitors device telemetry (location, battery level, speed, connectivity, etc.) and automatically sends alert notifications when safety conditions are triggered.


## Folder Structure
```
560-Lab-6/
│
├── Scripts/
│   ├── 
│   ├── 
│   └── 
│
├── requirements.txt
└── README.md
```

## Setup
### System Dependencies:
```
ThingsBoard: http://18.117.119.232:8080
OwnTracks: install on each device to be tracked
```

### Python Dependencies:

```
pip install -r requirements.txt
```

## How It Works

1. OwnTracks runs on each mobile device and publishes telemetry to the ThingsBoard server. 
2. ThingsBoard ingests and stores the telemetry data, making it accessible via REST API.
3. The dashboard on ThingsBoard displays real-time device information. 
4. Python script (NAME OF SCRIPT) fetches the latest telemetry for each registered device through ThingsBoard and runs it through a set of alert rules.
5. If a condition is triggered, an email notification is sent.
6. Alert deduplication ensures each alert is only sent once per incident and resets automatically when the condition clears.
