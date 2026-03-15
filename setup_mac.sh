#!/bin/bash

# Mac-compatible version of setup.sh
# Differences from Linux version:
#   - No sudo (real-time scheduling is skipped on macOS)

BRAND_BASE_DIR=$(pwd)
BRAND_MOD_DIR=$BRAND_BASE_DIR/../brand-modules/
export BRAND_BASE_DIR

conda activate rt

# Use /tmp/redis.sock instead of /var/run/redis.sock — the latter requires root
# on macOS, which we don't need since we're not setting real-time priorities.
alias booter='python supervisor/booter.py'
alias supervisor='python supervisor/supervisor.py -s /tmp/redis.sock'

export PATH=$(pwd)/bin:$PATH
