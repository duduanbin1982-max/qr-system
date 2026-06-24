#!/bin/bash
mkdir -p /home/dubin/qr-system/data/backups
cp /home/dubin/qr-system/data/production.db /home/dubin/qr-system/data/backups/production_$(date +%Y%m%d_%H%M%S).db
find /home/dubin/qr-system/data/backups -name '*.db' -mtime +30 -delete
