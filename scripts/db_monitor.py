#!/usr/bin/env python3
"""DB Growth Monitor — logs size daily, alerts on rapid growth."""
import os, json, time
from datetime import datetime

DB_PATH = "/home/dubin/qr-system/data/production.db"
LOG_DIR = "/home/dubin/qr-system/logs"
SIZE_LOG = os.path.join(LOG_DIR, "db_size_history.json")
ALERT_THRESHOLD_MB = 50
GROWTH_ALERT_MB = 10

os.makedirs(LOG_DIR, exist_ok=True)

size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
size_mb = round(size_bytes / (1024 * 1024), 2)
today = datetime.now().strftime("%Y-%m-%d")
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

history = []
if os.path.exists(SIZE_LOG):
    try:
        with open(SIZE_LOG) as f:
            history = json.load(f)
    except Exception:
        pass

history.append({"date": today, "ts": now, "size_mb": size_mb})
if len(history) > 90:
    history = history[-90:]

with open(SIZE_LOG, "w") as f:
    json.dump(history, f, indent=2)

# Alert check
if len(history) >= 2:
    prev = history[-2]
    growth = round(size_mb - prev["size_mb"], 1)
    if growth > GROWTH_ALERT_MB:
        alert_msg = f"[{now}] DB grew {growth}MB since {prev['date']} (now {size_mb}MB)"
        with open(os.path.join(LOG_DIR, "db_alerts.log"), "a") as af:
            af.write(alert_msg + "\n")

if size_mb > ALERT_THRESHOLD_MB:
    alert_msg = f"[{now}] DB size {size_mb}MB exceeds threshold {ALERT_THRESHOLD_MB}MB"
    with open(os.path.join(LOG_DIR, "db_alerts.log"), "a") as af:
        af.write(alert_msg + "\n")

print(f"[{now}] DB size: {size_mb} MB (records: {len(history)})")
