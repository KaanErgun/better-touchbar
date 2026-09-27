#!/usr/bin/env bash
# Install/update on the T2 MacBook over SSH (needs passwordless sudo there).
# Usage: scripts/deploy.sh [user@host]
set -euo pipefail
cd "$(dirname "$0")/.."
host=${1:-kaanergun@kaanergun-MacBookPro.local}
./scripts/check.sh
scp -q touchbar_cat.py cat_art.py touchbar-cat.service "$host":/tmp/
scp -q -r tiny-dfr system "$host":/tmp/
ssh "$host" 'set -e
  sudo -n install -D -m 755 /tmp/touchbar_cat.py /usr/local/lib/touchbar-cat/touchbar_cat.py
  sudo -n install -m 644 /tmp/cat_art.py /usr/local/lib/touchbar-cat/cat_art.py
  sudo -n install -m 644 /tmp/touchbar-cat.service /etc/systemd/system/touchbar-cat.service
  sudo -n install -d /etc/tiny-dfr
  sudo -n install -m 644 -t /etc/tiny-dfr /tmp/tiny-dfr/*
  sudo -n install -m 755 /tmp/system/t2-touchbar-fix /usr/local/sbin/t2-touchbar-fix
  sudo -n install -m 644 /tmp/system/t2-touchbar-fix.service /etc/systemd/system/t2-touchbar-fix.service
  rm -r /tmp/touchbar_cat.py /tmp/cat_art.py /tmp/touchbar-cat.service /tmp/tiny-dfr /tmp/system
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable --quiet touchbar-cat.service
  sudo -n systemctl reenable --quiet t2-touchbar-fix.service   # (re)links the sleep targets too
  sudo -n systemctl restart touchbar-cat.service   # ends cat mode, which restarts tiny-dfr
  sudo -n systemctl try-restart tiny-dfr.service   # pick up a changed layout
  echo "touchbar-cat: $(systemctl is-active touchbar-cat.service) tiny-dfr: $(systemctl is-active tiny-dfr.service)"'
