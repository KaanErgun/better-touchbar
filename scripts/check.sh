#!/usr/bin/env bash
# Canonical local gate. Hardware-free: DRM ABI sizes, every gesture pose, pixel mapping.
# Not covered: real Touch Bar output — run `touchbar_cat.py --demo 30` on the Mac for that.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m py_compile touchbar_cat.py cat_art.py
python3 touchbar_cat.py --self-test
bash -n scripts/deploy.sh
sh -n system/t2-touchbar-fix
# tiny-dfr layout: TOML parses, every key has an Action, every Icon exists (packaged or ours)
python3 - <<'PY'
import glob, os, tomllib, xml.etree.ElementTree as ET
PACKAGED = {"brightness_low", "brightness_high", "backlight_low", "backlight_high", "fast_rewind",
            "play_pause", "fast_forward", "volume_off", "volume_down", "volume_up", "mic_off", "search"}
cfg = tomllib.load(open("tiny-dfr/config.toml", "rb"))
ours = {os.path.basename(p)[:-4] for p in glob.glob("tiny-dfr/*.svg")}
for p in glob.glob("tiny-dfr/*.svg"):
    ET.parse(p)
for key in cfg["MediaLayerKeys"]:
    assert key.get("Action"), key
    assert "Icon" not in key or key["Icon"] in PACKAGED | ours, f"missing icon {key['Icon']}"
print(f"tiny-dfr config OK: {len(cfg['MediaLayerKeys'])} keys, {len(ours)} own icons")
PY
