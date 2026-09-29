#!/usr/bin/env python3
"""better-touchbar: a Touch Bar daemon for T2 MacBooks on Ubuntu (takes over from tiny-dfr).

What is on the bar, first match wins:
  Fn held   F1-F12
  overlay   a slider (brightness, keyboard light, volume), quick settings or Turkish letters
  media     transport, title and a seekable position bar while the focused app plays media
            (or, without the GNOME Shell extension, whenever something plays)
  app       buttons for the focused app ([apps] in touchbar.toml) + the compact strip
  control   the control strip
After idle_seconds without input, and with nothing playing, the idle cat (cat_art.py) comes out.
Runs as root under systemd; session-side state (media, volume, focus, settings) comes from
tb_agent.py, which it runs as the logged-in user. An independent implementation: no tiny-dfr
code (K-001). Design decisions K-xxx: development.md.
"""
import argparse
import fcntl
import json
import os
import random
import select
import signal
import subprocess
import sys
import time
import tomllib

import cat_art as art
import tb_hw as hw

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = "/etc/touchbar/touchbar.toml"
KEYBOARD = "Apple Inc. Apple Internal Keyboard / Trackpad"
TOUCHPAD = "Apple Inc. Touch Bar Display Touchpad"
TOUCH_MAX_X = 32767
SPACING = 16
CAT_WIDTH = art.W * art.SCALE
CONTENT = ("icon", "text", "time", "battery")
ACTIONS = {"key": None, "slider": ("brightness", "keyboard", "volume"),
           "layer": ("quick", "turkish"), "toggle": ("mic",)}
SLIDER_ICONS = {"brightness": "light_mode", "keyboard": "backlight_high", "volume": "volume_up"}
SLIDER_CLOSE, LAYER_CLOSE, PAUSED_KEEP = 3.0, 8.0, 10.0
ACCENT = (0.13, 0.42, 0.85)   # a quick setting that is on
ALERT = (0.80, 0.18, 0.18)    # live microphone
# Turkish letters via the "Turkish (Alt-Q)" layout (tr+alt): US keys, Turkish on AltGr (K-005).
# (lower, upper, base key); a Shift held on the real keyboard makes the AltGr combo uppercase.
TURKISH = (("ş", "Ş", "S"), ("ğ", "Ğ", "G"), ("ü", "Ü", "U"), ("ö", "Ö", "O"),
           ("ç", "Ç", "C"), ("ı", "I", "I"), ("İ", "İ", "I"))


# --- config + geometry ----------------------------------------------------------------
def norm_app(app):
    return (app or "").lower().removesuffix(".desktop")


def same_app(a, b):
    a, b = norm_app(a), norm_app(b)
    return bool(a and b) and (a == b or a in b or b in a)


def _prepare(button, where):
    shown = [k for k in CONTENT if k in button]
    acts = [k for k in ACTIONS if k in button]
    if len(shown) != 1 or len(acts) > 1:
        raise ValueError(f"{where}: needs one of {CONTENT} and at most one of {tuple(ACTIONS)}: {button}")
    button["do"] = None
    if acts:
        act, arg = acts[0], button[acts[0]]
        if act == "key":
            keys = [arg] if isinstance(arg, str) else arg
            button["do"] = ("key", [hw.key_code(k) for k in keys])
        elif arg not in ACTIONS[act]:
            raise ValueError(f"{where}: {act} must be one of {ACTIONS[act]}: {button}")
        else:
            button["do"] = (act, arg)


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for layer in ("control", "compact", "fn"):
        for button in cfg.setdefault(layer, []):
            _prepare(button, layer)
    cfg["apps"] = {norm_app(app): buttons for app, buttons in cfg.get("apps", {}).items()}
    for app, buttons in cfg["apps"].items():
        for button in buttons:
            _prepare(button, f"apps.{app}")
    return cfg


def layout(buttons, length, spacing=SPACING):
    """[(x0, x1)] per button along the bar; `stretch` weights, fixed gaps between buttons."""
    units = sum(b.get("stretch", 1) for b in buttons)
    unit = (length - spacing * (len(buttons) - 1)) / units
    rects, x = [], 0.0
    for b in buttons:
        w = unit * b.get("stretch", 1)
        rects.append((x, x + w))
        x += w + spacing
    return rects


def hit(rects, x):
    """Button under bar position x; a touch in a gap goes to the nearer neighbour."""
    for i, (_, x1) in enumerate(rects):
        if x < x1 + SPACING / 2:
            return i
    return len(rects) - 1 if rects else None


def clamp(v):
    return max(0.0, min(1.0, v))


def turkish_codes(index, shifted):
    lower, _, base = TURKISH[index]
    k = hw.KEYS
    if lower == "ı" and shifted:    # uppercase dotless i is plain I: Shift is already held
        return [k[base]]
    if lower == "İ":                # AltGr+Shift+i
        return [k["RIGHTALT"], k["LEFTSHIFT"], k[base]]
    return [k["RIGHTALT"], k[base]]


def build_strips(rows, bar_height, mirror):
    """A cat pose as one XRGB8888 row per bar column (same map as tb_hw.bar_to_buffer)."""
    top = (bar_height - art.H * art.SCALE) // 2
    strips = []
    for col in range(CAT_WIDTH):
        src_col = col // art.SCALE
        if mirror:
            src_col = art.W - 1 - src_col
        row = bytearray(bar_height * 4)
        for y in range(art.H * art.SCALE):
            ch = rows[y // art.SCALE][src_col]
            if ch != ".":
                across = bar_height - 1 - (top + y)
                r, g, b = art.PALETTE[ch]
                row[across * 4:across * 4 + 4] = bytes((b, g, r, 0))
        strips.append(bytes(row))
    return strips


# --- session helper -------------------------------------------------------------------
def session_user():
    """(name, uid) owning the active user session on seat0, or None (greeter, nobody)."""
    def loginctl(*args):
        return subprocess.run(["loginctl", *args], capture_output=True, text=True, timeout=3).stdout
    try:
        sid = loginctl("show-seat", "seat0", "-p", "ActiveSession", "--value").strip()
        if not sid:
            return None
        props = dict(line.split("=", 1) for line in
                     loginctl("show-session", sid, "-p", "Name", "-p", "User", "-p", "Class").splitlines()
                     if "=" in line)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if props.get("Class") != "user":
        return None
    return props["Name"], int(props["User"])


class AgentLink:
    """tb_agent.py as the session user (K-003); restarted when it dies or the session changes."""

    def __init__(self):
        self.proc, self.buf, self.next_try = None, b"", 0.0

    def ensure(self):
        if self.proc and self.proc.poll() is None:
            return
        now = time.monotonic()
        if now < self.next_try:
            return
        self.next_try, self.proc, self.buf = now + 10, None, b""
        user = session_user()
        if not user:
            return
        name, uid = user
        env = [f"XDG_RUNTIME_DIR=/run/user/{uid}", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus"]
        self.proc = subprocess.Popen(
            ["runuser", "-u", name, "--", "env", *env, sys.executable, os.path.join(HERE, "tb_agent.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        os.set_blocking(self.proc.stdout.fileno(), False)
        print(f"agent started for {name}", flush=True)

    def fd(self):
        return self.proc.stdout.fileno() if self.proc and self.proc.poll() is None else None

    def send(self, **cmd):
        if self.fd() is None:
            return False
        try:
            self.proc.stdin.write((json.dumps(cmd) + "\n").encode())
            self.proc.stdin.flush()
            return True
        except OSError:
            return False

    def messages(self):
        try:
            data = os.read(self.proc.stdout.fileno(), 65536)
        except BlockingIOError:
            return []
        except OSError:
            data = b""
        if not data:  # agent exited (session ended, crash): try again later
            self.proc.kill()
            self.proc = None
            return [{"t": "gone"}]
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out


class Inputs:
    """Internal keyboard + trackpad (activity, Fn, Shift) and the Touch Bar touchpad (grabbed)."""

    def __init__(self):
        self.devs = {}  # fd -> (path, kind)

    def refresh(self):
        wanted = {}
        for name, paths in hw.input_devices().items():
            kind = "touch" if name == TOUCHPAD else "kbd" if name == KEYBOARD else None
            if kind:
                wanted.update(dict.fromkeys(paths, kind))
        current = {path: fd for fd, (path, _) in self.devs.items()}
        for path, fd in current.items():
            if path not in wanted:
                self._drop(fd)
        for path, kind in wanted.items():
            if path in current:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                continue
            if kind == "touch":
                try:  # otherwise GNOME also treats the bar as a pointer device
                    fcntl.ioctl(fd, hw.EVIOCGRAB, 1)
                except OSError:
                    pass
            self.devs[fd] = (path, kind)

    def _drop(self, fd):
        self.devs.pop(fd, None)
        try:
            os.close(fd)
        except OSError:
            pass

    def read(self, timeout, extra=()):
        """([(kind, type, code, value)], ready extra fds) within timeout seconds."""
        fds = [*self.devs, *[f for f in extra if f is not None]]
        if not fds:
            time.sleep(max(timeout, 0))
            return [], []
        ready, _, _ = select.select(fds, [], [], max(timeout, 0))
        events = []
        for fd in ready:
            if fd not in self.devs:
                continue
            kind = self.devs[fd][1]
            try:
                while True:
                    data = os.read(fd, hw.EVENT.size * 64)
                    for off in range(0, len(data) - hw.EVENT.size + 1, hw.EVENT.size):
                        _, _, etype, code, value = hw.EVENT.unpack_from(data, off)
                        events.append((kind, etype, code, value))
            except BlockingIOError:
                pass
            except OSError:  # device went away (resume, Touch Bar re-enumeration)
                self._drop(fd)
        return events, [fd for fd in ready if fd not in self.devs]


# --- the daemon -------------------------------------------------------------------------
class TouchBar:
    def __init__(self, args, cfg):
        self.args, self.cfg = args, cfg
        self.keyboard = hw.Keyboard()
        self.inputs = Inputs()
        self.agent = AgentLink()
        self.display = None
        self.init_state()

    def init_state(self):
        self.fn = self.shift = False
        self.overlay, self.overlay_until, self.overlay_timeout = None, 0.0, 0.0
        self.drag, self.pressed, self.held = None, None, []
        self.touch_x, self.touch_down, self.was_down = 0, False, False
        self.ignore_touch = False  # K-009: the tap that woke the bar from the cat presses nothing
        self.last_input = time.monotonic()
        self.dirty, self.shown_minute = True, None
        self.values = {"volume": None, "brightness": None, "keyboard": None}
        self.muted = False
        self.media, self.media_dismissed, self.paused_at = None, False, 0.0
        self.focus = None          # focused app id; None = unknown (no Shell extension)
        self.settings = {"dnd": False, "night_light": False, "mic_muted": None}
        self.pending_volume, self.volume_sent = None, 0.0
        self.last_scan = 0.0

    # --- what is shown -----------------------------------------------------------------
    def playing(self):
        return bool(self.media and self.media.get("status") == "Playing")

    def media_mode(self):
        m = self.media
        if not m or self.media_dismissed:
            return False
        if self.focus is not None:  # K-010: Shell extension present, follow the focused window
            return same_app(m.get("app"), self.focus) and m.get("status") in ("Playing", "Paused")
        return self.playing() or (m.get("status") == "Paused"
                                  and time.monotonic() - self.paused_at < PAUSED_KEEP)

    def current(self):
        """(layer name, widgets) of what the bar shows right now."""
        if self.fn:
            return "fn", self.cfg["fn"]
        if self.overlay:
            kind = self.overlay[0]
            if kind == "slider":
                return "slider", self.slider_widgets(self.overlay[1])
            return kind, self.quick_widgets() if kind == "quick" else self.turkish_widgets()
        if self.media_mode():
            return "media", self.media_widgets()
        app = self.cfg["apps"].get(norm_app(self.focus)) if self.focus else None
        if app:
            return "app", self.decorate([*app, *self.cfg["compact"]])
        return "control", self.decorate(self.cfg["control"])

    def decorate(self, buttons):
        """Live state on config buttons: play/pause icon, microphone colour."""
        out = []
        for b in buttons:
            if b["do"] == ("key", [hw.KEYS["PLAYPAUSE"]]):
                b = {**b, "icon": "pause" if self.playing() else "play_arrow"}
            elif b["do"] == ("toggle", "mic"):
                muted = self.settings["mic_muted"]
                b = {**b, "icon": "mic_off" if muted else "mic", "bg": ALERT if muted is False else None}
            elif b["do"] == ("slider", "volume") and self.muted:
                b = {**b, "icon": "volume_off"}
            out.append(b)
        return out

    def slider_widgets(self, kind):
        v = self.values.get(kind) or 0.0
        icon = "volume_off" if kind == "volume" and self.muted else SLIDER_ICONS[kind]
        return [{"icon": icon, "do": ("close",)},
                {"track": True, "stretch": 12, "value": v, "label": f"{round(v * 100)}%",
                 "do": ("track", kind)},
                {"icon": "close", "do": ("close",)}]

    def quick_widgets(self):
        def on(state):
            return ACCENT if state else None
        wifi, bt, s = hw.rfkill_enabled("wlan"), hw.rfkill_enabled("bluetooth"), self.settings
        return [
            {"icon": "wifi" if wifi else "wifi_off", "bg": on(wifi), "do": ("toggle", "wifi")},
            {"icon": "bluetooth" if bt else "bluetooth_disabled", "bg": on(bt), "do": ("toggle", "bluetooth")},
            {"icon": "do_not_disturb_on" if s["dnd"] else "notifications", "bg": on(s["dnd"]),
             "do": ("toggle", "dnd")},
            {"icon": "bedtime", "bg": on(s["night_light"]), "do": ("toggle", "night_light")},
            {"icon": "mic_off" if s["mic_muted"] else "mic",
             "bg": ALERT if s["mic_muted"] is False else None, "do": ("toggle", "mic")},
            {"icon": "close", "do": ("close",)},
        ]

    def turkish_widgets(self):
        letters = [{"text": upper if self.shift else lower, "size": 24, "do": ("char", i)}
                   for i, (lower, upper, _) in enumerate(TURKISH)]
        return [*letters, {"icon": "close", "do": ("close",)}]

    def media_position(self):
        m = self.media
        if self.drag and self.drag["type"] == "scrub":
            return self.drag["frac"] * (m.get("length") or 0)
        pos = m.get("position") or 0
        if m.get("status") == "Playing":
            pos += time.monotonic() - m.get("at", time.monotonic())
        return min(pos, m.get("length") or pos)

    def media_widgets(self):
        m, playing = self.media, self.playing()
        seekable = bool(m.get("can_seek") and m.get("length"))
        return [
            {"icon": "skip_previous", "do": ("media", "Previous")},
            {"icon": "pause" if playing else "play_arrow", "do": ("media", "PlayPause")},
            {"icon": "skip_next", "do": ("media", "Next")},
            {"title": m.get("title") or m.get("app") or "", "artist": m.get("artist", ""),
             "stretch": 4, "bare": True, "do": None},
            {"scrub": True, "stretch": 7, "length": m.get("length") or 0,
             "position": self.media_position(), "can_seek": seekable,
             "do": ("scrub",) if seekable else None},
            {"icon": "volume_off" if self.muted else "volume_up", "do": ("slider", "volume")},
            {"icon": "close", "do": ("close",)},
        ]

    def frame(self):
        name, widgets = self.current()
        rects = layout(widgets, self.display.length)
        for w, (x0, x1) in zip(widgets, rects):
            if "track" in w:
                w["span"] = (x0 + 24, x1 - 110)
            elif "scrub" in w:
                w["span"] = (x0 + 90, x1 - 90)
        return name, widgets, rects

    # --- display -----------------------------------------------------------------------
    def open_display(self):
        while True:
            try:
                self.display = hw.Display(self.args.flip_along)
                hw.set_bar_brightness(self.cfg.get("bar_brightness", 2))
                self.dirty = True
                return
            except (OSError, RuntimeError) as e:
                print(f"display not ready ({e}), retrying", flush=True)
                time.sleep(2)
                self.inputs.refresh()

    def reopen_display(self, why):
        print(f"display lost ({why}), reopening", flush=True)
        if self.display:
            try:
                self.display.close()
            except OSError:
                pass
        self.display = None
        subprocess.run(["udevadm", "settle", "--timeout=10"], check=False)
        self.open_display()

    def render(self):
        import tb_ui
        _, widgets, rects = self.frame()
        cr = self.display.context()
        tb_ui.draw(cr, widgets, rects, self.pressed)
        del cr
        self.display.flush()
        self.dirty, self.shown_minute = False, int(time.time() // 60)

    # --- input -------------------------------------------------------------------------
    def handle(self, events):
        k = hw.KEYS
        for kind, etype, code, value in events:
            if kind == "kbd":
                if etype == hw.EV_KEY and value in (0, 1):
                    if code == k["FN"]:
                        self.release()  # never leave a key of the old layer stuck down
                        self.fn, self.dirty = bool(value), True
                    elif code in (k["LEFTSHIFT"], k["RIGHTSHIFT"]):
                        self.shift = bool(value)
                        self.dirty = self.dirty or self.overlay == ("turkish",)
            elif etype == hw.EV_ABS and code == hw.ABS_X:
                self.touch_x = value
            elif etype == hw.EV_KEY and code == hw.BTN_TOUCH:
                self.touch_down = bool(value)
            elif etype == hw.EV_SYN and code == hw.SYN_REPORT:
                self.touch_frame()

    def bar_x(self):
        x = self.touch_x * self.display.length / TOUCH_MAX_X
        return self.display.length - x if self.args.touch_flip else x

    def touch_frame(self):
        if self.touch_down and not self.was_down:
            self.press()
        elif self.touch_down:
            self.move()
        elif self.was_down:
            self.release()
            self.ignore_touch = False
        self.was_down = self.touch_down

    def press(self):
        if self.ignore_touch or self.display is None:
            return
        x = self.bar_x()
        _, widgets, rects = self.frame()
        i = hit(rects, x)
        if i is None:
            return
        w, act = widgets[i], widgets[i].get("do")
        self.touch_overlay()
        if not act:
            return
        self.pressed, self.dirty, kind = i, True, act[0]
        if kind == "key":
            self.hold(act[1])
        elif kind == "char":
            self.hold(turkish_codes(act[1], self.shift))
        elif kind == "slider":  # open it; a finger that keeps moving adjusts right away
            v = self.read_value(act[1])
            self.open_overlay(("slider", act[1]), SLIDER_CLOSE)
            span = next(w2["span"] for w2 in self.frame()[1] if "track" in w2)
            self.drag = {"type": "slider", "kind": act[1], "x0": x, "v0": v or 0.0,
                         "width": span[1] - span[0], "rel": True}
        elif kind == "track":
            a, b = w["span"]
            self.drag = {"type": "slider", "kind": act[1], "span": (a, b), "rel": False}
            self.set_value(act[1], (x - a) / (b - a))
        elif kind == "scrub":
            a, b = w["span"]
            self.drag = {"type": "scrub", "span": (a, b), "frac": clamp((x - a) / (b - a))}
        elif kind == "close":
            self.close_overlay()
        elif kind == "media":
            self.media_action(act[1])
        elif kind == "toggle":
            self.toggle(act[1])
        elif kind == "layer":
            self.open_overlay((act[1],), LAYER_CLOSE)

    def move(self):
        d = self.drag
        if not d or self.display is None:
            return
        x = self.bar_x()
        self.touch_overlay()
        if d["type"] == "slider":
            if d["rel"]:
                self.set_value(d["kind"], d["v0"] + (x - d["x0"]) / d["width"])
            else:
                a, b = d["span"]
                self.set_value(d["kind"], (x - a) / (b - a))
        else:
            a, b = d["span"]
            d["frac"], self.dirty = clamp((x - a) / (b - a)), True

    def release(self):
        d, self.drag = self.drag, None
        if d and d["type"] == "scrub" and self.media:
            position = d["frac"] * (self.media.get("length") or 0)
            self.agent.send(c="seek", position=position)
            self.media.update(position=position, at=time.monotonic())
        elif d and d["kind"] == "volume":
            self.flush_volume(force=True)
        if self.held:
            self.keyboard.send(self.held, 0)
            self.held = []
        if self.pressed is not None:
            self.pressed, self.dirty = None, True

    def hold(self, codes):
        self.held = codes
        if codes:
            self.keyboard.send(codes, 1)

    def tap(self, name):
        code = [hw.KEYS[name]]
        self.keyboard.send(code, 1)
        self.keyboard.send(code, 0)

    # --- actions -----------------------------------------------------------------------
    def open_overlay(self, overlay, seconds):
        self.overlay, self.overlay_timeout = overlay, seconds
        self.overlay_until = time.monotonic() + seconds
        self.pressed, self.dirty = None, True

    def touch_overlay(self):
        if self.overlay:
            self.overlay_until = time.monotonic() + self.overlay_timeout

    def close_overlay(self):
        if self.overlay:
            self.overlay = None
        elif self.media_mode():
            self.media_dismissed = True
        self.pressed, self.dirty = None, True

    def read_value(self, kind):
        if kind == "brightness":
            v = hw.read_level(hw.screen_backlight() or "")
        elif kind == "keyboard":
            v = hw.read_level(hw.keyboard_backlight() or "")
        else:
            v = self.values["volume"]
        self.values[kind] = v
        return v

    def set_value(self, kind, v):
        v = clamp(v)
        self.values[kind], self.dirty = v, True
        if kind == "brightness" and hw.screen_backlight():
            hw.write_level(hw.screen_backlight(), v, floor=0.02)  # never a black screen
        elif kind == "keyboard" and hw.keyboard_backlight():
            hw.write_level(hw.keyboard_backlight(), v)
        elif kind == "volume":
            self.pending_volume = v
            self.flush_volume()

    def flush_volume(self, force=False):
        now = time.monotonic()
        if self.pending_volume is not None and (force or now - self.volume_sent > 0.05):
            if self.agent.send(c="volume", value=self.pending_volume):
                self.volume_sent, self.pending_volume = now, None

    def media_action(self, action):
        if not self.agent.send(c="media", action=action):  # no session helper: media keys
            self.tap({"PlayPause": "PLAYPAUSE", "Next": "NEXTSONG", "Previous": "PREVIOUSSONG"}[action])

    def toggle(self, what):
        if what in ("wifi", "bluetooth"):
            kind = "wlan" if what == "wifi" else "bluetooth"
            hw.rfkill_set(kind, not hw.rfkill_enabled(kind))
        else:  # dnd, night_light, mic live in the user's session
            self.agent.send(c="toggle", what=what)
        self.dirty = True

    # --- session helper messages -------------------------------------------------------
    def on_agent(self, msg):
        t = msg.get("t")
        if t == "media":
            old, now = self.media or {}, time.monotonic()
            if not msg.get("name"):
                self.media = None
            else:
                if msg.get("title") != old.get("title") or (
                        msg.get("status") == "Playing" and old.get("status") != "Playing"):
                    self.media_dismissed = False
                if msg.get("status") == "Paused" and old.get("status") == "Playing":
                    self.paused_at = now
                self.media = {**msg, "at": now}
            self.dirty = True
        elif t == "volume":
            self.values["volume"], self.muted = msg.get("value"), bool(msg.get("muted"))
            self.dirty = True
        elif t == "focus":
            self.focus, self.dirty = msg.get("app"), True
        elif t == "settings":
            self.settings.update({k: msg[k] for k in self.settings if k in msg})
            self.dirty = True
        elif t == "gone":  # helper exited: drop session state until it is back
            self.media, self.focus, self.dirty = None, None, True
        elif t == "error":
            print(f"agent: {msg.get('error')}", flush=True)

    def poll(self, timeout):
        """Wait up to timeout for input; session helper messages are handled on the way."""
        if time.monotonic() - self.last_scan > 5:  # also while the cat is out
            self.inputs.refresh()
            self.last_scan = time.monotonic()
        self.agent.ensure()
        events, ready = self.inputs.read(timeout, extra=[self.agent.fd()])
        if ready:
            for msg in self.agent.messages():
                self.on_agent(msg)
        return events

    # --- idle cat ----------------------------------------------------------------------
    def run_cat(self, stop_after=None):
        """Cat scenes until input arrives or media starts playing; returns the waking events."""
        d, rng, cache, last = self.display, random.Random(), {}, None
        hw.set_bar_brightness(self.cfg.get("cat_brightness", 1))
        d.map[:] = bytes(len(d.map))
        d.flush()
        started = time.monotonic()
        print("cat mode on", flush=True)
        while True:
            x = rng.randrange(0, d.length - CAT_WIDTH)
            mirror = rng.random() < 0.5
            name = rng.choice([g for g in art.GESTURES if g != last])
            last = name
            for kw, ms in art.RISE + art.GESTURES[name] + art.SINK:
                key = (art.draw(**kw), mirror)
                if key not in cache:
                    cache[key] = build_strips(key[0], d.across, mirror)
                for i, strip in enumerate(cache[key]):
                    d.write_col(x + i, strip)
                d.flush(x, x + CAT_WIDTH)
                events = self.poll(ms / 1000)
                if events or self.playing():
                    return events
            if stop_after and time.monotonic() - started > stop_after:
                return []
            events = self.poll(rng.uniform(2, 6))
            if events or self.playing():
                return events

    def wake(self, events):
        print("cat mode off", flush=True)
        hw.set_bar_brightness(self.cfg.get("bar_brightness", 2))
        self.ignore_touch, self.dirty = True, True
        self.last_input = time.monotonic()
        self.handle(events)
        if not self.touch_down:
            self.ignore_touch = False

    # --- main loop ---------------------------------------------------------------------
    def run(self):
        self.inputs.refresh()
        self.open_display()
        idle = self.cfg.get("idle_seconds", 60)
        while True:
            try:
                now = time.monotonic()
                if self.overlay and now >= self.overlay_until and not self.touch_down:
                    self.overlay, self.dirty = None, True
                if self.shown_minute != int(time.time() // 60):
                    self.dirty = True  # clock and battery
                if self.dirty:
                    self.render()
                self.flush_volume()
                idle_left = idle - (now - self.last_input)
                if idle_left <= 0 and not self.touch_down and not self.playing():  # K-009
                    self.wake(self.run_cat())
                    continue
                # <= 5 s so poll() rescans hot-plugged inputs (resume, re-enumeration)
                timeout = min(60 - time.time() % 60 + 0.05, max(idle_left, 1.0), 5.0)
                if self.overlay:
                    timeout = min(timeout, max(self.overlay_until - now, 0.05))
                if self.pending_volume is not None:
                    timeout = min(timeout, 0.05)
                events = self.poll(timeout)
                if events:
                    self.last_input = time.monotonic()
                    self.handle(events)
            except OSError as e:  # the card went away (resume, re-enumeration)
                self.reopen_display(e)

    def close(self):
        self.release()
        self.keyboard.close()
        if self.display:
            self.display.close()


# --- tests ----------------------------------------------------------------------------
class _Offscreen:
    """Display stand-in for tests: the real layout maths without DRM."""
    across, length = 60, 2008


def _state(cfg):
    bar = TouchBar.__new__(TouchBar)
    bar.cfg, bar.display = cfg, _Offscreen()
    bar.args = argparse.Namespace(flip_along=False, touch_flip=False)
    bar.init_state()
    return bar


def self_test(config):
    """Hardware-free checks (run by scripts/check.sh on any machine)."""
    import struct
    sizes = {hw.MODEINFO: 68, hw.CARD_RES: 64, hw.GET_CONNECTOR: 80, hw.GET_ENCODER: 20,
             hw.CRTC: 104, hw.CREATE_DUMB: 32, hw.MAP_DUMB: 16, hw.FB_CMD: 28, hw.FB_DIRTY: 24,
             hw.CLIP: 8, hw.UINPUT_USER_DEV: 1116}
    for fmt, size in sizes.items():
        assert struct.calcsize(fmt) == size, (fmt, struct.calcsize(fmt), size)
    assert hw.EVENT.size == 24
    assert (hw.DIRTYFB, hw.CREATE_DUMB_IOC, hw.SETCRTC) == (0xC01864B1, 0xC02064B2, 0xC06864A2)
    assert (hw.EVIOCGRAB, hw.UI_SET_KEYBIT) == (0x40044590, 0x40045565)
    k = hw.KEYS
    assert (k["ESC"], k["1"], k["0"], k["Q"], k["A"], k["Z"], k["M"]) == (1, 2, 11, 16, 30, 44, 50)
    assert (k["F1"], k["F10"], k["F11"], k["F12"], k["F13"], k["F24"]) == (59, 68, 87, 88, 183, 194)
    assert (k["GRAVE"], k["SLASH"], k["RIGHTALT"], k["PAGEUP"]) == (41, 53, 100, 104)
    assert hw.key_code("KEY_brightnessdown") == 224
    assert hw.bar_to_buffer(0, 0, 60, 2008) == (60, 0)
    assert hw.bar_to_buffer(10, 5, 60, 2008) == (55, 10)
    assert hw.bar_to_buffer(10, 5, 60, 2008, flip_along=True) == (55, 1998)
    cfg = load_config(config)
    layers = [cfg["control"], cfg["fn"], *[[*a, *cfg["compact"]] for a in cfg["apps"].values()]]
    for buttons in layers:
        rects = layout(buttons, 2008)
        assert abs(rects[-1][1] - 2008) < 1e-6 and rects[0][0] == 0
        assert all(abs(b[0] - a[1] - SPACING) < 1e-6 for a, b in zip(rects, rects[1:]))
        assert [hit(rects, (x0 + x1) / 2) for x0, x1 in rects] == list(range(len(rects)))
    rects = layout(cfg["control"], 2008)
    assert hit(rects, rects[0][1] + SPACING / 2 - 1) == 0 and hit(rects, rects[0][1] + SPACING / 2 + 1) == 1
    assert cfg["control"][4]["do"] == ("key", [k["LEFTMETA"], k["A"]])
    assert set(cfg["apps"]) >= {"code", "google-chrome", "org.gnome.terminal"}
    try:
        _prepare({"icon": "x", "slider": "nope"}, "test")
        raise AssertionError("bad slider accepted")
    except ValueError:
        pass
    assert same_app("google-chrome", "google-chrome.desktop") and not same_app("vlc", "code.desktop")
    assert not same_app("", "code.desktop")
    assert turkish_codes(0, False) == [k["RIGHTALT"], k["S"]]
    assert turkish_codes(5, True) == [k["I"]] and turkish_codes(6, False) == [k["RIGHTALT"], k["LEFTSHIFT"], k["I"]]
    # which layer wins (K-010: media follows focus when the extension is there)
    bar = _state(cfg)
    assert bar.current()[0] == "control"
    bar.focus = "code.desktop"
    assert bar.current()[0] == "app"
    bar.on_agent({"t": "media", "name": "org.mpris.MediaPlayer2.vlc", "status": "Playing", "app": "vlc",
                  "title": "t", "length": 100, "position": 10, "can_seek": True})
    assert bar.current()[0] == "app", "media of an unfocused player stays out of the way"
    bar.on_agent({"t": "focus", "app": "vlc.desktop"})
    assert bar.current()[0] == "media"
    bar.close_overlay()
    assert bar.current()[0] == "control" and bar.media_dismissed
    bar.on_agent({"t": "media", "name": "org.mpris.MediaPlayer2.vlc", "status": "Playing", "app": "vlc",
                  "title": "next", "length": 100, "position": 0, "can_seek": True})
    assert bar.current()[0] == "media", "a new title brings the controls back"
    bar.focus = None  # no Shell extension: anything playing shows the controls
    bar.on_agent({"t": "focus", "app": None})
    assert bar.current()[0] == "media"
    bar.open_overlay(("slider", "volume"), SLIDER_CLOSE)
    assert bar.current()[0] == "slider"
    bar.fn = True
    assert bar.current()[0] == "fn"
    art.self_test()
    top = (60 - art.H * art.SCALE) // 2
    across = 60 - 1 - (top + 15 * art.SCALE)  # nose cell (row 15, col 12)
    pink = bytes(reversed(art.PALETTE["p"]))
    assert build_strips(art.draw(), 60, False)[12 * art.SCALE][across * 4:across * 4 + 3] == pink
    assert build_strips(art.draw(), 60, True)[(art.W - 1 - 12) * art.SCALE][across * 4:across * 4 + 3] == pink
    assert not any(any(s) for s in build_strips(art.draw(**art.SINK[-1][0]), 60, False))
    print("self-test OK")


DEMO_MEDIA = {"t": "media", "name": "org.mpris.MediaPlayer2.vlc", "status": "Playing", "app": "vlc",
              "title": "Big Buck Bunny", "artist": "Blender Foundation", "length": 596,
              "position": 131, "can_seek": True}


def _layers(bar):
    """name -> function putting bar into that layer (tests and screenshots share these)."""
    return {"control": lambda: None, "fn": lambda: setattr(bar, "fn", True),
            "slider": lambda: bar.open_overlay(("slider", "volume"), 3),
            "quick": lambda: bar.open_overlay(("quick",), 8),
            "turkish": lambda: bar.open_overlay(("turkish",), 8),
            "media": lambda: bar.on_agent(DEMO_MEDIA),
            "app": lambda: bar.on_agent({"t": "focus", "app": "code.desktop"})}


def _draw_layer(bar, name, matrix):
    import cairo
    import tb_ui
    bar.init_state()
    bar.values["volume"], bar.settings["mic_muted"], bar.settings["dnd"] = 0.4, False, True
    _layers(bar)[name]()
    layer, widgets, rects = bar.frame()
    assert layer == name, (layer, name)
    w, h = (60, 2008) if matrix else (2008, 60)
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    cr = cairo.Context(surface)
    if matrix:
        cr.set_matrix(cairo.Matrix(0, 1, -1, 0, 60, 0))
    tb_ui.draw(cr, widgets, rects, pressed=None)
    surface.flush()
    return surface


def render_test(config):
    """Draw every layer off-screen with the real matrix (needs pycairo; run on the Mac)."""
    bar = _state(load_config(config))
    for name in _layers(bar):
        surface = _draw_layer(bar, name, matrix=True)
        data, stride = surface.get_data(), surface.get_stride()
        x0, _ = layout(bar.frame()[1], 2008)[0]  # first widget is always a key: its background
        bx, by = hw.bar_to_buffer(int(x0 + 10), 6, 60, 2008)
        assert data[by * stride + (bx - 1) * 4 + 2] > 0, f"{name}: first key not drawn"
        lit = sum(1 for i in range(2, len(data), 4) if data[i] > 128)
        assert lit > 500, f"{name}: almost nothing bright on the bar ({lit})"
    print("render-test OK")


def screenshots(config, out):
    """PNG of every layer plus the cat, drawn by the real code (for the README)."""
    import cairo
    os.makedirs(out, exist_ok=True)
    bar = _state(load_config(config))
    for name in _layers(bar):
        _draw_layer(bar, name, matrix=False).write_to_png(os.path.join(out, f"{name}.png"))
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 2008, 60)
    data, stride = surface.get_data(), surface.get_stride()
    scenes = [(260, "yavas_goz_kirpma", 5), (900, "pati_yalama", 3), (1560, "uyuklama", 4)]
    for x, gesture, step in scenes:  # a few cats mid-gesture, painted cell by cell
        rows = art.draw(**art.GESTURES[gesture][step][0])
        for y in range(art.H * art.SCALE):
            for c in range(CAT_WIDTH):
                ch = rows[y // art.SCALE][c // art.SCALE]
                if ch != ".":
                    r, g, b = art.PALETTE[ch]
                    i = y * stride + (x + c) * 4
                    data[i:i + 4] = bytes((b, g, r, 0))
    surface.mark_dirty()
    surface.write_to_png(os.path.join(out, "cat.png"))
    print(f"screenshots written to {out}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=CONFIG)
    p.add_argument("--flip-along", action="store_true", help="panel's left end is buffer row 2008")
    p.add_argument("--touch-flip", action="store_true", help="touch x runs right to left")
    p.add_argument("--cat-demo", type=float, metavar="SECONDS", help="show the cat now, then exit")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--render-test", action="store_true")
    p.add_argument("--screenshots", metavar="DIR", help="write a PNG of every layer to DIR")
    args = p.parse_args()
    if not os.path.exists(args.config):  # running from a checkout
        args.config = os.path.join(HERE, "touchbar.toml")
    if args.self_test:
        return self_test(args.config)
    if args.render_test:
        return render_test(args.config)
    if args.screenshots:
        return screenshots(args.config, args.screenshots)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    bar = TouchBar(args, load_config(args.config))
    try:
        if args.cat_demo:
            bar.inputs.refresh()
            bar.open_display()
            bar.run_cat(stop_after=args.cat_demo)
        else:
            bar.run()
    finally:
        bar.close()


if __name__ == "__main__":
    main()
