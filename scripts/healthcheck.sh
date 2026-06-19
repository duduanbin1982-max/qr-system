#!/bin/bash
# QR System Health Check
URL="https://127.0.0.1/api/auth/info"
HTTP_CODE=$(curl -sk -o /dev/null -w '%{http_code}' --connect-timeout 10 "$URL" 2>/dev/null)
if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "401" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALERT: QR System health check failed (HTTP $HTTP_CODE)" >> /home/dubin/qr-system/logs/healthcheck.log
fi
