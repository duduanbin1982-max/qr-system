#!/bin/bash
# QR System Heartbeat Monitor
# Usage: */5 * * * * /home/dubin/qr-system/scripts/heartbeat.sh
# Status logged to logs/heartbeat.log

LOG="/home/dubin/qr-system/logs/heartbeat.log"
URL="https://127.0.0.1/api/health"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

RESP=$(curl -sk --connect-timeout 5 --max-time 10 "$URL" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ] && echo "$RESP" | grep -q '"status":"ok"'; then
    echo "[$TIMESTAMP] OK - $RESP" >> "$LOG"
    exit 0
else
    echo "[$TIMESTAMP] FAIL (exit=$EXIT_CODE) - $RESP" >> "$LOG"
    # TODO: add notification (dingtalk/webhook/email) here
    exit 1
fi
