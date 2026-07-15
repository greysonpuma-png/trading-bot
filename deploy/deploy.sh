#!/bin/bash
# One-shot (and re-runnable) deploy of the swing bot to a fresh Ubuntu 24.04
# DigitalOcean droplet. Usage:  ./deploy.sh <droplet-ip>
#
# Uses SSH on PORT 443 (not 22) because some networks (e.g. campus WiFi) block
# outbound port 22. The droplet's sshd was configured to listen on both.
#
# Does everything: server hardening basics, code sync (including .env and the
# permanent trade logs), venv, systemd service. Safe to re-run to push updates.
set -euo pipefail

IP="${1:?usage: deploy.sh <droplet-ip>}"
PORT=443
KEY="$HOME/.ssh/tradingbot_do"
SRC="$HOME/Documents/trading-bot/trading_agent_swing"
UNIT="$(cd "$(dirname "$0")" && pwd)/trading-bot.service"
RUN="ssh -i $KEY -p $PORT -o StrictHostKeyChecking=accept-new root@$IP"

echo "== 1/5 base server setup =="
$RUN 'bash -s' <<'EOF'
set -e
timedatectl set-timezone America/Denver
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq python3-venv python3-pip rsync ufw
ufw allow OpenSSH
ufw allow 443/tcp   # SSH also listens here; MUST be open before enabling ufw
ufw --force enable
id -u bot >/dev/null 2>&1 || adduser --disabled-password --gecos "" bot
EOF

echo "== 2/5 swap file (512MB droplet insurance) =="
$RUN 'bash -s' <<'EOF'
set -e
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
EOF

echo "== 3/5 sync code + .env + permanent trade logs =="
# agent.jsonl debug traces are big and disposable; picks/journal/proposals are
# the permanent record and move with the bot.
rsync -az -e "ssh -i $KEY -p $PORT" \
  --exclude '.venv*' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'logs/agent.jsonl*' --exclude 'logs/autostart.*' \
  "$SRC/" root@"$IP":/home/bot/trading_agent_swing/

echo "== 4/5 python env =="
$RUN 'bash -s' <<'EOF'
set -e
cd /home/bot/trading_agent_swing
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
chown -R bot:bot /home/bot/trading_agent_swing
EOF

echo "== 5/5 systemd service =="
scp -q -i "$KEY" -P $PORT "$UNIT" root@"$IP":/etc/systemd/system/trading-bot.service
$RUN 'systemctl daemon-reload && systemctl enable --now trading-bot && systemctl restart trading-bot'
sleep 8
$RUN 'systemctl status trading-bot --no-pager | head -6; echo; cat /home/bot/trading_agent_swing/logs/heartbeat.txt 2>/dev/null; echo'

echo
echo "Done. Check on it any time with:"
echo "  ssh -i ~/.ssh/tradingbot_do -p 443 root@$IP journalctl -u trading-bot -n 50"
