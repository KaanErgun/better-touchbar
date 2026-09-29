#!/usr/bin/env bash
# Install/update the Touch Bar daemon on the T2 MacBook over SSH (needs passwordless sudo there).
# Usage: scripts/deploy.sh [ssh-host]
set -euo pipefail
cd "$(dirname "$0")/.."
host=${1:-mbp-ubuntu}
./scripts/check.sh
tar --no-xattrs --no-mac-metadata -czf - touchbar.py tb_hw.py tb_ui.py cat_art.py touchbar.toml tiny-dfr system \
  | ssh "$host" 'rm -rf /tmp/tb-deploy && mkdir /tmp/tb-deploy && tar -xzf - -C /tmp/tb-deploy'
ssh "$host" 'set -e
  cd /tmp/tb-deploy
  L=/usr/local/lib/touchbar
  sudo -n install -d $L /etc/touchbar /etc/tiny-dfr /etc/systemd/system/tiny-dfr.service.d
  sudo -n install -m 644 -t $L touchbar.py tb_hw.py tb_ui.py cat_art.py
  sudo -n install -m 644 touchbar.toml /etc/touchbar/touchbar.toml
  sudo -n install -m 644 -t /etc/tiny-dfr tiny-dfr/*   # fallback layout + icons both daemons use
  sudo -n install -m 755 system/t2-touchbar-fix /usr/local/sbin/t2-touchbar-fix
  sudo -n install -m 644 -t /etc/systemd/system \
    system/touchbar.service system/touchbar-fallback.service system/t2-touchbar-fix.service
  sudo -n install -m 644 system/tiny-dfr-50-touchbar.conf \
    /etc/systemd/system/tiny-dfr.service.d/50-touchbar.conf
  python3 $L/touchbar.py --config /etc/touchbar/touchbar.toml --render-test   # before touching services
  sudo -n systemctl daemon-reload   # tiny-dfr drop-in active before anything may start tiny-dfr
  if [ -e /etc/systemd/system/touchbar-cat.service ]; then   # one-time: the cat-only daemon
    sudo -n systemctl disable --now touchbar-cat.service
    sudo -n rm -rf /etc/systemd/system/touchbar-cat.service /usr/local/lib/touchbar-cat
    sudo -n systemctl daemon-reload
  fi
  sudo -n rm -f /run/touchbar-fallback
  sudo -n systemctl stop tiny-dfr.service
  sudo -n systemctl enable --quiet touchbar.service
  sudo -n systemctl reenable --quiet t2-touchbar-fix.service   # also links the sleep targets
  sudo -n systemctl restart touchbar.service
  sleep 3
  echo "touchbar: $(systemctl is-active touchbar.service) tiny-dfr: $(systemctl is-active tiny-dfr.service)"
  rm -rf /tmp/tb-deploy'
