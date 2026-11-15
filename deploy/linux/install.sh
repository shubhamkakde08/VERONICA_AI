#!/usr/bin/env bash
# ReportBot on Ubuntu 22.04/24.04 without Docker:  sudo bash deploy/linux/install.sh
set -euo pipefail
apt-get update
apt-get install -y python3 python3-venv python3-pip libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-noto-core fonts-noto-ui-core
id reportbot >/dev/null 2>&1 || useradd --system --home /opt/reportbot --shell /usr/sbin/nologin reportbot
mkdir -p /opt/reportbot && cp -r . /opt/reportbot/ && cd /opt/reportbot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
sed -i 's/host\.docker\.internal/127.0.0.1/g' .env
mkdir -p output logs && chown -R reportbot:reportbot /opt/reportbot
sudo -u reportbot .venv/bin/python -m tools.manage init
cp deploy/linux/reportbot.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now reportbot
echo "Running. Internet: install cloudflared and run 'cloudflared service install <TOKEN>' (same token steps as Windows)."
