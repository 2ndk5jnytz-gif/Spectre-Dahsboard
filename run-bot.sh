#!/usr/bin/env bash

cd "$(dirname "$0")" || exit 1

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
fi

while true; do
  python3 start_latest.py >> bot.log 2>&1
  printf '[%s] start_latest.py stopped; restarting in 10 seconds\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> bot.log
  sleep 10
done
