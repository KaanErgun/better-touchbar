#!/usr/bin/env bash
# Regenerate icons/ from Google's Material Symbols (Rounded, filled), recoloured white for the
# black Touch Bar (K-007). The SVGs in icons/ are generated: edit this list, do not edit the files.
# Usage: scripts/fetch-icons.sh
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=https://raw.githubusercontent.com/google/material-design-icons/master
ICONS=(
  settings light_mode backlight_high overview_key apps screenshot_region
  skip_previous play_arrow pause skip_next volume_off volume_up mic mic_off
  wifi wifi_off bluetooth bluetooth_disabled do_not_disturb_on notifications bedtime close
  terminal refresh arrow_back arrow_forward add search content_copy content_paste
  cancel chevron_left chevron_right link keyboard_command_key comment format_align_left
  bug_report backspace
)
mkdir -p icons
for name in "${ICONS[@]}"; do
  svg=$(curl -fsS "$BASE/symbols/web/$name/materialsymbolsrounded/${name}_fill1_24px.svg" 2>/dev/null \
     || curl -fsS "$BASE/symbols/web/$name/materialsymbolsrounded/${name}_24px.svg")
  printf '%s\n' "${svg/<svg /<svg fill=\"white\" }" > "icons/$name.svg"
done
curl -fsS "$BASE/LICENSE" > icons/LICENSE
echo "fetched ${#ICONS[@]} icons into icons/ (Material Symbols, Apache-2.0, see icons/LICENSE)"
