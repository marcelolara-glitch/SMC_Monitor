#!/bin/bash
set -e

source ~/.bashrc

export SMC_TELEGRAM_TOKEN="${SMC_TELEGRAM_TOKEN}"
export SMC_TELEGRAM_CHAT_ID="${SMC_TELEGRAM_CHAT_ID}"

source ~/SMC_Monitor/venv/bin/activate

cd ~/SMC_Monitor
exec python main.py
