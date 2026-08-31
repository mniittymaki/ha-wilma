#!/bin/bash
# Deploy wilma integration to Home Assistant
set -e

HA_HOST="${HA_HOST:-matti@ssh-home.mazaha.fi}"
HA_PORT="${HA_PORT:-444}"
HA_PATH="/home/matti/config/ha/custom_components/wilma"
LOCAL="custom_components/wilma/"

echo "Deploying to $HA_HOST:$HA_PATH (port $HA_PORT)"
scp -P "$HA_PORT" "$LOCAL"*.py "$LOCAL"*.json "$HA_HOST:/tmp/wilma_deploy/"
ssh -p "$HA_PORT" "$HA_HOST" "sudo cp /tmp/wilma_deploy/* $HA_PATH/ && rm -rf /tmp/wilma_deploy"
echo "Files copied. Restart HA to apply changes."
