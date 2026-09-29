"""Drawing the Touch Bar with pycairo, Pango and librsvg (all preinstalled on Ubuntu).

Everything is drawn in bar coordinates (x along the bar, y down from the top edge); the
Display's cairo matrix takes care of the panel's rotation. A layer is a list of widget dicts
plus their [x0, x1) rects; touchbar.py owns all geometry and state, this module only paints.

Widget content (exactly one): icon, text, time, battery, track (slider), scrub (media
position), title (media title/artist). Optional: bg (rgb) for toggles/alerts, bare (no key).
"""
import os
import time

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Rsvg", "2.0")
from gi.repository import Pango, PangoCairo, Rsvg  # noqa: E402

HEIGHT = 60
ICON_SIZE = 36
ICON_DIRS = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons"),
             "/usr/local/share/touchbar/icons", "/etc/tiny-dfr", "/usr/share/tiny-dfr")
KEY, KEY_PRESSED = (0.20, 0.20, 0.20), (0.42, 0.42, 0.42)
ACCENT = (0.13, 0.42, 0.85)   # a quick setting that is on
ALERT = (0.80, 0.18, 0.18)    # live microphone
BATTERY = "/sys/class/power_supply/BAT0"

_icons = {}


def _font(size, bold=True):
    return Pango.FontDescription(f"Ubuntu {'Bold ' if bold else ''}{size}")


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


def _layout(cr, text, size=17, bold=True, width=None):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(_font(size, bold))
    layout.set_text(text, -1)
    if width:
        layout.set_width(int(width * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
    return layout


def _text(cr, text, cx, cy, rgb=(1, 1, 1), size=17, bold=True):
    layout = _layout(cr, text, size, bold)
    w, h = layout.get_pixel_size()
    cr.set_source_rgb(*rgb)
    cr.move_to(cx - w / 2, cy - h / 2)
    PangoCairo.show_layout(cr, layout)
    return w


def _draw_icon(cr, name, cx, cy, size=ICON_SIZE):
    handle = _icon(name)
    if handle is None:  # missing icon: show its name instead of an empty key
        return _text(cr, name[:6], cx, cy, size=12)
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
    tw, _ = _layout(cr, label).get_pixel_size()
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


def _bar(cr, a, b, frac, cy, knob=True):
    """A horizontal slider rail from a to b, filled up to frac (0-1), with a knob."""
    cr.set_source_rgb(0.28, 0.28, 0.28)
    _rounded(cr, a, cy - 4, b - a, 8, 4)
    cr.fill()
    fx = a + (b - a) * max(0.0, min(1.0, frac))
    cr.set_source_rgb(0.93, 0.93, 0.93)
    _rounded(cr, a, cy - 4, max(fx - a, 8), 8, 4)
    cr.fill()
    if knob:
        cr.arc(fx, cy, 12, 0, 6.2832)
        cr.fill()


def _clock(seconds):
    seconds = max(0, int(seconds or 0))
    h, rest = divmod(seconds, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"


def draw(cr, widgets, rects, pressed=None):
    """Paint one layer: black background, then every widget in its rect."""
    cr.set_source_rgb(0, 0, 0)
    cr.paint()
    cy = HEIGHT / 2
    for i, (w, (x0, x1)) in enumerate(zip(widgets, rects)):
        if "track" in w:
            a, b = w["span"]
            _bar(cr, a, b, w["value"] or 0, cy)
            _text(cr, w.get("label", ""), (b + x1) / 2, cy)
            continue
        if "scrub" in w:
            a, b = w["span"]
            length, pos = w.get("length") or 0, w.get("position") or 0
            _bar(cr, a, b, pos / length if length else 0, cy, knob=w.get("can_seek", True))
            _text(cr, _clock(pos), (x0 + a) / 2, cy, size=14)
            _text(cr, "-" + _clock(length - pos) if length else "", (b + x1) / 2, cy, size=14)
            continue
        if "title" in w:
            layout = _layout(cr, w["title"] or "", 15, True, x1 - x0 - 16)
            sub = _layout(cr, w.get("artist") or "", 12, False, x1 - x0 - 16)
            (_, th), (_, sh) = layout.get_pixel_size(), sub.get_pixel_size()
            top = cy - (th + (sh if w.get("artist") else 0)) / 2
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(x0 + 8, top)
            PangoCairo.show_layout(cr, layout)
            if w.get("artist"):
                cr.set_source_rgb(0.7, 0.7, 0.7)
                cr.move_to(x0 + 8, top + th)
                PangoCairo.show_layout(cr, sub)
            continue
        if not w.get("bare"):
            bg = KEY_PRESSED if i == pressed else w.get("bg") or KEY
            if i == pressed and w.get("bg"):
                bg = tuple(min(1.0, c + 0.2) for c in w["bg"])
            cr.set_source_rgb(*bg)
            _rounded(cr, x0, 3, x1 - x0, HEIGHT - 6, 8)
            cr.fill()
        cx = (x0 + x1) / 2
        if "icon" in w:
            _draw_icon(cr, w["icon"], cx, cy)
        elif "text" in w:
            _text(cr, w["text"], cx, cy, size=w.get("size", 17))
        elif "time" in w:
            _text(cr, time.strftime(w["time"]), cx, cy)
        elif w.get("battery"):
            _draw_battery(cr, cx, cy)
