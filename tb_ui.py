"""Drawing the Touch Bar layers with pycairo, Pango and librsvg (all preinstalled on Ubuntu).

Everything is drawn in bar coordinates (x along the bar, y down from the top edge); the
Display's cairo matrix takes care of the panel's rotation.
"""
import os
import time

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Rsvg", "2.0")
from gi.repository import Pango, PangoCairo, Rsvg  # noqa: E402

HEIGHT = 60
ICON_SIZE = 38
ICON_DIRS = ("/etc/tiny-dfr", "/usr/share/tiny-dfr")  # our icons first, then the packaged set
BUTTON, BUTTON_PRESSED = 0.20, 0.42
FONT = Pango.FontDescription("Ubuntu Bold 17")
BATTERY = "/sys/class/power_supply/BAT0"

_icons = {}


def _icon(name):
    if name not in _icons:
        paths = [os.path.join(d, name + ".svg") for d in ICON_DIRS]
        _icons[name] = next((Rsvg.Handle.new_from_file(p) for p in paths if os.path.exists(p)), None)
    return _icons[name]


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def _text(cr, text, cx, cy, rgb=(1, 1, 1)):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(FONT)
    layout.set_text(text, -1)
    w, h = layout.get_pixel_size()
    cr.set_source_rgb(*rgb)
    cr.move_to(cx - w / 2, cy - h / 2)
    PangoCairo.show_layout(cr, layout)
    return w


def _draw_icon(cr, name, cx, cy, size=ICON_SIZE):
    handle = _icon(name)
    if handle is None:  # missing icon: show its name instead of an empty button
        return _text(cr, name[:6], cx, cy)
    rect = Rsvg.Rectangle()
    rect.x, rect.y, rect.width, rect.height = cx - size / 2, cy - size / 2, size, size
    handle.render_document(cr, rect)


def battery_state():
    """(percent, charging) from sysfs; (None, False) when there is no battery."""
    try:
        with open(BATTERY + "/capacity") as f:
            pct = int(f.read())
        with open(BATTERY + "/status") as f:
            charging = f.read().strip() in ("Charging", "Full")
        return pct, charging
    except OSError:
        return None, False


def _draw_battery(cr, cx, cy):
    pct, charging = battery_state()
    if pct is None:
        return _text(cr, "--", cx, cy)
    color = (0.35, 0.85, 0.35) if charging else (0.95, 0.3, 0.3) if pct < 10 else (1, 1, 1)
    body_w, body_h, gap = 30, 15, 6
    label = f"{pct}%"
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(FONT)
    layout.set_text(label, -1)
    tw, _ = layout.get_pixel_size()
    x = cx - (body_w + 3 + gap + tw) / 2
    cr.set_source_rgb(*color)
    cr.set_line_width(2)
    _rounded(cr, x, cy - body_h / 2, body_w, body_h, 3)
    cr.stroke()
    cr.rectangle(x + body_w, cy - 3, 3, 6)  # terminal nub
    cr.fill()
    cr.rectangle(x + 3, cy - body_h / 2 + 3, (body_w - 6) * pct / 100, body_h - 6)
    cr.fill()
    _text(cr, label, x + body_w + 3 + gap + tw / 2, cy, color)


def draw_buttons(cr, buttons, rects, pressed=None):
    """One full layer: black background, a rounded key per button, its icon/text/value."""
    cr.set_source_rgb(0, 0, 0)
    cr.paint()
    cy = HEIGHT / 2
    for i, (button, (x0, x1)) in enumerate(zip(buttons, rects)):
        shade = BUTTON_PRESSED if i == pressed else BUTTON
        cr.set_source_rgb(shade, shade, shade)
        _rounded(cr, x0, 3, x1 - x0, HEIGHT - 6, 8)
        cr.fill()
        cx = (x0 + x1) / 2
        if "icon" in button:
            _draw_icon(cr, button["icon"], cx, cy)
        elif "text" in button:
            _text(cr, button["text"], cx, cy)
        elif "time" in button:
            _text(cr, time.strftime(button["time"]), cx, cy)
        elif button.get("battery"):
            _draw_battery(cr, cx, cy)
