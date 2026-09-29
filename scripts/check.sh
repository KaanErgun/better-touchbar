#!/usr/bin/env bash
# Canonical local gate. Hardware-free: DRM/evdev/uinput ABI sizes, key table, bar<->buffer
# mapping, layout + hit testing, the touchbar.toml layout, every cat pose.
# Not covered here: drawing (pycairo/Pango/librsvg are only on the Mac) -- deploy.sh runs
# `touchbar.py --render-test` there before touching services; real panel output needs eyes.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m py_compile touchbar.py tb_hw.py tb_ui.py tb_agent.py cat_art.py tools/*.py
python3 touchbar.py --config touchbar.toml --self-test
bash -n scripts/deploy.sh install.sh scripts/fetch-icons.sh
sh -n system/t2-touchbar-fix
# project docs: CLAUDE.md stays a short rulebook (~/Developments rule: <= 120 lines)
[ "$(wc -l < CLAUDE.md)" -le 120 ] || { echo "CLAUDE.md is longer than 120 lines" >&2; exit 1; }
for doc in development.md dev-log.md docs/PROGRESS.md; do [ -s "$doc" ] || { echo "missing $doc" >&2; exit 1; }; done
# layouts: every icon exists (icons/ or tiny-dfr's packaged set); the extension metadata parses
python3 - <<'PY'
import glob, os, tomllib, xml.etree.ElementTree as ET
PACKAGED = {"brightness_low", "brightness_high", "backlight_low", "backlight_high", "fast_rewind",
            "play_pause", "fast_forward", "volume_off", "volume_down", "volume_up", "mic_off", "search"}
cfg = tomllib.load(open("tiny-dfr/config.toml", "rb"))
ours = {os.path.basename(p)[:-4] for p in glob.glob("icons/*.svg")}
for p in glob.glob("icons/*.svg"):
    ET.parse(p)
import json; json.load(open("gnome-extension/better-touchbar@kaanergun.github.io/metadata.json"))
mine = tomllib.load(open("touchbar.toml", "rb"))
buttons = [b for k in ("control", "compact", "fn") for b in mine[k]] + [b for a in mine["apps"].values() for b in a]
missing = {b["icon"] for b in buttons if "icon" in b} - ours - PACKAGED
assert not missing, f"touchbar.toml icons missing from icons/: {missing}"
for key in cfg["MediaLayerKeys"]:
    assert key.get("Action"), key
    assert "Icon" not in key or key["Icon"] in PACKAGED | ours, f"missing icon {key['Icon']}"
print(f"layouts OK: {len(buttons)} touchbar.toml buttons, {len(cfg['MediaLayerKeys'])} fallback keys, {len(ours)} icons")
PY
