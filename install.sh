#!/usr/bin/env bash
# Install, update or remove better-touchbar on a T2 MacBook running Ubuntu 24.04 or later.
#
# Usage: ./install.sh [--turkish] [--update-config]
#        ./install.sh --uninstall
#   --turkish        switch the keyboard layout to "Turkish (Alt-Q)": US keys with ş ğ ü ö ç ı İ
#                    on AltGr (right Option), which the Touch Bar's TR letters type through
#   --update-config  overwrite /etc/touchbar/touchbar.toml (a copy of the old one is kept)
set -euo pipefail
cd "$(dirname "$0")"

LIB=/usr/local/lib/touchbar
UNITS=/etc/systemd/system
EXT=better-touchbar@kaanergun.github.io
DESKTOP_USER=${SUDO_USER:-$USER}
TURKISH=0 UPDATE_CONFIG=0 UNINSTALL=0
for arg in "$@"; do
  case $arg in
    --turkish) TURKISH=1 ;;
    --update-config) UPDATE_CONFIG=1 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\033[1m[%s]\033[0m %s\n' "$1" "$2"; }

as_user() {  # run in the desktop user's session (GSettings, Shell extensions)
  local uid; uid=$(id -u "$DESKTOP_USER")
  sudo -u "$DESKTOP_USER" env XDG_RUNTIME_DIR="/run/user/$uid" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" "$@"
}
ext_dir() { echo "$(getent passwd "$DESKTOP_USER" | cut -d: -f6)/.local/share/gnome-shell/extensions/$EXT"; }

if [ "$UNINSTALL" = 1 ]; then
  step 1/2 "removing better-touchbar"
  sudo systemctl disable --now touchbar.service 2>/dev/null || true
  sudo rm -rf "$LIB" /etc/touchbar "$UNITS/touchbar.service" "$UNITS/touchbar-fallback.service" \
    "$UNITS/tiny-dfr.service.d/50-touchbar.conf" /run/touchbar-fallback
  as_user rm -rf "$(ext_dir)"
  step 2/2 "handing the Touch Bar back to tiny-dfr"
  sudo systemctl daemon-reload
  sudo systemctl start tiny-dfr.service 2>/dev/null || echo "  tiny-dfr is not installed"
  exit 0
fi

step 1/7 "checking dependencies (python3-gi, pycairo, librsvg, Pango: preinstalled on Ubuntu desktop)"
missing=$(for p in python3-gi python3-gi-cairo python3-cairo gir1.2-rsvg-2.0 gir1.2-pango-1.0; do
  dpkg-query -W -f='${Status}\n' "$p" 2>/dev/null | grep -q "ok installed" || echo "$p"; done)
[ -z "$missing" ] || sudo apt-get install -y $missing

step 2/7 "installing the daemon, icons and config"
sudo install -d "$LIB/icons" /etc/touchbar "$UNITS/tiny-dfr.service.d"
sudo install -m 644 -t "$LIB" touchbar.py tb_hw.py tb_ui.py tb_agent.py cat_art.py
sudo install -m 644 -t "$LIB/icons" icons/*.svg icons/LICENSE
if [ ! -e /etc/touchbar/touchbar.toml ]; then
  sudo install -m 644 touchbar.toml /etc/touchbar/touchbar.toml
elif cmp -s touchbar.toml /etc/touchbar/touchbar.toml; then
  :  # already current
elif [ "$UPDATE_CONFIG" = 1 ]; then
  sudo cp /etc/touchbar/touchbar.toml "/etc/touchbar/touchbar.toml.$(date +%Y%m%d-%H%M%S)"
  sudo install -m 644 touchbar.toml /etc/touchbar/touchbar.toml
else
  sudo install -m 644 touchbar.toml /etc/touchbar/touchbar.toml.dist
  echo "  kept your /etc/touchbar/touchbar.toml (the shipped one is touchbar.toml.dist)"
fi
if [ -d /usr/share/tiny-dfr ]; then  # tiny-dfr stays as the fallback, with a matching layout
  sudo install -d /etc/tiny-dfr
  sudo install -m 644 tiny-dfr/config.toml /etc/tiny-dfr/config.toml
  sudo install -m 644 -t /etc/tiny-dfr icons/overview_key.svg icons/apps.svg icons/screenshot_region.svg
fi

step 3/7 "testing the drawing code on this machine"
python3 "$LIB/touchbar.py" --config /etc/touchbar/touchbar.toml --render-test
python3 "$LIB/tb_agent.py" --self-test

step 4/7 "installing systemd units"
sudo install -m 755 system/t2-touchbar-fix /usr/local/sbin/t2-touchbar-fix
sudo install -m 644 -t "$UNITS" system/touchbar.service system/touchbar-fallback.service \
  system/t2-touchbar-fix.service
sudo install -m 644 system/tiny-dfr-50-touchbar.conf "$UNITS/tiny-dfr.service.d/50-touchbar.conf"
sudo systemctl daemon-reload  # tiny-dfr's drop-in is active before anything can start it

step 5/7 "GNOME Shell extension (tells the daemon which app has focus)"
as_user install -d "$(ext_dir)"
as_user install -m 644 -t "$(ext_dir)" "gnome-extension/$EXT/metadata.json" "gnome-extension/$EXT/extension.js"
as_user python3 - "$EXT" <<'PY'
import sys
from gi.repository import Gio
s = Gio.Settings.new("org.gnome.shell")
if sys.argv[1] not in s.get_strv("enabled-extensions"):
    s.set_strv("enabled-extensions", s.get_strv("enabled-extensions") + [sys.argv[1]])
s.set_boolean("disable-user-extensions", False)
PY

step 6/7 "keyboard layout"
if [ "$TURKISH" = 1 ]; then
  as_user gsettings set org.gnome.desktop.input-sources sources "[('xkb', 'tr+alt')]"
  echo "  Turkish (Alt-Q): US keys, ş ğ ü ö ç ı İ on AltGr"
else
  echo "  unchanged (use --turkish for the Touch Bar's TR letters)"
fi

step 7/7 "starting touchbar.service (tiny-dfr steps aside)"
sudo rm -f /run/touchbar-fallback
sudo systemctl stop tiny-dfr.service 2>/dev/null || true
sudo systemctl enable --quiet touchbar.service
sudo systemctl reenable --quiet t2-touchbar-fix.service  # also runs after every resume
sudo systemctl restart touchbar.service
sleep 3
echo "touchbar: $(systemctl is-active touchbar.service)"
echo "Log out and back in once so GNOME Shell loads the focus extension."
