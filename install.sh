#!/usr/bin/env bash
# install.sh — install, update or remove better-touchbar on this T2 MacBook (Ubuntu 24.04+).
# Usage:
#   ./install.sh [install] [--turkish] [--update-config]   install or update (the default verb)
#   ./install.sh uninstall                                  remove it; tiny-dfr takes the bar back
#   ./install.sh status                                     read-only: services, helper, extension
#   --turkish        keyboard layout "Turkish (Alt-Q)": US keys, ş ğ ü ö ç ı İ on AltGr (K-005)
#   --update-config  replace an edited /etc/touchbar/touchbar.toml (a dated copy is kept, K-008)
set -euo pipefail

LIB=/usr/local/lib/touchbar
UNITS=/etc/systemd/system
EXT=better-touchbar@kaanergun.github.io
BACKUP_ROOT=/var/backups/better-touchbar
STAMP=$(date +%Y%m%d-%H%M%S)
DESKTOP_USER=${SUDO_USER:-$USER}

if [ -t 1 ]; then GREEN=$'\033[32m' YELLOW=$'\033[33m' RED=$'\033[31m' BOLD=$'\033[1m' RESET=$'\033[0m'
else GREEN='' YELLOW='' RED='' BOLD='' RESET=''; fi
step() { printf '\n%s[%s] %s%s\n' "$BOLD" "$1" "$2" "$RESET"; }
ok()   { printf '  %s✅ %s%s\n' "$GREEN" "$*" "$RESET"; }
warn() { printf '  %s⚠️  %s%s\n' "$YELLOW" "$*" "$RESET"; }
fail() { printf '  %s❌ %s%s\n' "$RED" "$*" "$RESET"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$SCRIPT_DIR"
usage() { sed -n '3,8p' "$SCRIPT_DIR/install.sh" >&2; exit 1; }

VERB=install TURKISH=0 UPDATE_CONFIG=0
for arg in "$@"; do
  case $arg in
    install|uninstall|status) VERB=$arg ;;
    --uninstall) VERB=uninstall ;;  # v0.1.0 spelling
    --turkish) TURKISH=1 ;;
    --update-config) UPDATE_CONFIG=1 ;;
    *) usage ;;
  esac
done

as_user() {  # run in the desktop user's session (GSettings, Shell extensions)
  local uid; uid=$(id -u "$DESKTOP_USER")
  sudo -u "$DESKTOP_USER" env XDG_RUNTIME_DIR="/run/user/$uid" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" "$@"
}
ext_dir() { echo "$(getent passwd "$DESKTOP_USER" | cut -d: -f6)/.local/share/gnome-shell/extensions/$EXT"; }

CHANGED=0 BACKED_UP=0
backup() {  # keep a dated copy of an installed file before it is replaced or removed
  [ -e "$1" ] || return 0
  sudo install -d "$BACKUP_ROOT/$STAMP$(dirname "$1")"
  sudo cp -a "$1" "$BACKUP_ROOT/$STAMP$1"
  BACKED_UP=$((BACKED_UP + 1))
}
put() {  # put MODE SRC DEST: idempotent install, backing up whatever it replaces
  if sudo cmp -s "$2" "$3" 2>/dev/null; then return 0; fi
  backup "$3"
  sudo install -D -m "$1" "$2" "$3"
  CHANGED=$((CHANGED + 1))
}

summary() {
  printf '\n%s%s: OK%s  %d file(s) changed' "$GREEN" "$1" "$RESET" "$CHANGED"
  [ "$BACKED_UP" -gt 0 ] && printf ', %d backed up in %s' "$BACKED_UP" "$BACKUP_ROOT/$STAMP"
  printf '\n'
}

do_status() {
  step 1/1 "better-touchbar on $(hostname) (read-only)"
  for s in touchbar tiny-dfr t2-touchbar-fix; do printf '  %-18s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null)"; done
  printf '  %-18s %s\n' "fallback flag" "$([ -e /run/touchbar-fallback ] && echo SET || echo no)"
  printf '  %-18s %s\n' "session helper" "$(pgrep -fa tb_agent.py | grep -vc runuser || true) running"  # runuser wraps it
  printf '  %-18s %s\n' "focus extension" "$(as_user gnome-extensions info "$EXT" 2>/dev/null | awk '/State/{print $2}')"
}

do_uninstall() {
  step 1/3 "stopping touchbar.service"
  sudo systemctl disable --now touchbar.service 2>/dev/null || true
  ok "stopped"
  step 2/3 "removing files (backed up first)"
  for f in "$UNITS/touchbar.service" "$UNITS/touchbar-fallback.service" \
           "$UNITS/tiny-dfr.service.d/50-touchbar.conf" /etc/touchbar/touchbar.toml; do
    [ -e "$f" ] && { backup "$f"; sudo rm -f "$f"; CHANGED=$((CHANGED + 1)); }
  done
  sudo rm -rf "$LIB" /run/touchbar-fallback
  as_user rm -rf "$(ext_dir)"
  ok "daemon, units, config and the focus extension removed (t2-touchbar-fix stays: it serves tiny-dfr too)"
  step 3/3 "handing the Touch Bar back to tiny-dfr"
  sudo systemctl daemon-reload
  if sudo systemctl start tiny-dfr.service 2>/dev/null; then ok "tiny-dfr started"; else warn "tiny-dfr is not installed"; fi
  summary uninstall
}

do_install() {
  step 1/8 "dependencies (python3-gi, pycairo, librsvg, Pango: preinstalled on Ubuntu desktop, K-006)"
  missing=$(for p in python3-gi python3-gi-cairo python3-cairo gir1.2-rsvg-2.0 gir1.2-pango-1.0; do
    dpkg-query -W -f='${Status}\n' "$p" 2>/dev/null | grep -q "ok installed" || echo "$p"; done)
  if [ -n "$missing" ]; then sudo apt-get install -y $missing; ok "installed: $missing"; else ok "all present"; fi

  step 2/8 "daemon, icons and config"
  for f in touchbar.py tb_hw.py tb_ui.py tb_agent.py cat_art.py; do put 644 "$f" "$LIB/$f"; done
  for f in icons/*.svg icons/LICENSE; do put 644 "$f" "$LIB/$f"; done
  cfg=/etc/touchbar/touchbar.toml  # an edited config is never overwritten (K-008)
  if [ ! -e "$cfg" ] || [ "$UPDATE_CONFIG" = 1 ]; then put 644 touchbar.toml "$cfg"
  elif ! sudo cmp -s touchbar.toml "$cfg"; then
    put 644 touchbar.toml "$cfg.dist"
    warn "kept your $cfg (the shipped one is $cfg.dist)"
  fi
  if [ -d /usr/share/tiny-dfr ]; then  # tiny-dfr stays the fallback, with a matching layout (K-002)
    put 644 tiny-dfr/config.toml /etc/tiny-dfr/config.toml
    for i in overview_key apps screenshot_region; do put 644 "icons/$i.svg" "/etc/tiny-dfr/$i.svg"; done
  fi
  ok "$LIB, /etc/touchbar"

  step 3/8 "drawing test on this machine"
  python3 "$LIB/touchbar.py" --config "$cfg" --render-test | sed 's/^/  /'
  python3 "$LIB/tb_agent.py" --self-test | sed 's/^/  /'

  step 4/8 "systemd units"
  put 755 system/t2-touchbar-fix /usr/local/sbin/t2-touchbar-fix
  for u in touchbar.service touchbar-fallback.service t2-touchbar-fix.service; do put 644 "system/$u" "$UNITS/$u"; done
  put 644 system/tiny-dfr-50-touchbar.conf "$UNITS/tiny-dfr.service.d/50-touchbar.conf"
  sudo systemctl daemon-reload  # tiny-dfr's drop-in is active before anything can start it
  ok "units installed"

  step 5/8 "GNOME Shell focus extension (K-004)"
  for f in metadata.json extension.js; do
    as_user install -D -m 644 "gnome-extension/$EXT/$f" "$(ext_dir)/$f"
  done
  as_user python3 - "$EXT" <<'PY'
import sys
from gi.repository import Gio
s = Gio.Settings.new("org.gnome.shell")
if sys.argv[1] not in s.get_strv("enabled-extensions"):  # grep-guard: add once
    s.set_strv("enabled-extensions", s.get_strv("enabled-extensions") + [sys.argv[1]])
s.set_boolean("disable-user-extensions", False)
PY
  ok "enabled for $DESKTOP_USER (loads at the next login)"

  step 6/8 "keyboard layout"
  if [ "$TURKISH" = 1 ]; then
    as_user gsettings set org.gnome.desktop.input-sources sources "[('xkb', 'tr+alt')]"
    ok "Turkish (Alt-Q): US keys, ş ğ ü ö ç ı İ on AltGr"
  else
    ok "unchanged (--turkish enables the TR letters)"
  fi

  step 7/8 "starting touchbar.service (tiny-dfr steps aside)"
  sudo rm -f /run/touchbar-fallback
  sudo systemctl stop tiny-dfr.service 2>/dev/null || true
  sudo systemctl enable --quiet touchbar.service
  sudo systemctl reenable --quiet t2-touchbar-fix.service  # also runs after every resume
  sudo systemctl restart touchbar.service
  ok "restarted"

  step 8/8 "verify"
  sleep 3
  state=$(systemctl is-active touchbar.service || true)
  [ "$state" = active ] || fail "touchbar.service is $state (journalctl -u touchbar)"
  ok "touchbar.service active"
  summary install
  echo "Log out and back in once so GNOME Shell loads the focus extension."
}

case $VERB in
  install) do_install ;;
  uninstall) do_uninstall ;;
  status) do_status ;;
esac
