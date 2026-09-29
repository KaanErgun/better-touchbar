#!/usr/bin/env python3
"""Touch Bar daemon for T2 MacBooks on Linux (takes over from tiny-dfr).

Phase 1: the control strip and the Fn layer from touchbar.toml, keys typed through a uinput
keyboard, and the idle cat (cat_art.py) after idle_seconds without keyboard, trackpad or
Touch Bar input. Runs as root under systemd; tiny-dfr only comes back as the fallback when
this service keeps failing (touchbar-fallback.service).
"""
import argparse
import fcntl
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

CONFIG = "/etc/touchbar/touchbar.toml"
KEYBOARD = "Apple Inc. Apple Internal Keyboard / Trackpad"
TOUCHPAD = "Apple Inc. Touch Bar Display Touchpad"
TOUCH_MAX_X = 32767
SPACING = 16
CONTENT = ("icon", "text", "time", "battery")
CAT_WIDTH = art.W * art.SCALE


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for layer in ("control", "fn"):
        for button in cfg[layer]:
            shown = [k for k in CONTENT if k in button]
            if len(shown) != 1:
                raise ValueError(f"{layer}: a button needs exactly one of {CONTENT}: {button}")
            keys = button.get("key", [])
            button["codes"] = [hw.key_code(k) for k in ([keys] if isinstance(keys, str) else keys)]
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


class Inputs:
    """Internal keyboard + trackpad (activity, Fn) and the Touch Bar touchpad (grabbed)."""

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

    def read(self, timeout):
        """[(kind, type, code, value)] that arrived within timeout seconds."""
        if not self.devs:
            time.sleep(max(timeout, 0))
            return []
        ready, _, _ = select.select(list(self.devs), [], [], max(timeout, 0))
        events = []
        for fd in ready:
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
        return events


class TouchBar:
    def __init__(self, args, cfg):
        self.args, self.cfg = args, cfg
        self.keyboard = hw.Keyboard()
        self.inputs = Inputs()
        self.display = None
        self.layer = "control"
        self.pressed, self.held = None, []
        self.touch_x, self.touch_down, self.was_down = 0, False, False
        self.ignore_touch = False  # the tap that woke the bar from the cat presses nothing
        self.last_input = time.monotonic()
        self.dirty, self.shown_minute = True, None

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
        buttons = self.cfg[self.layer]
        cr = self.display.context()
        tb_ui.draw_buttons(cr, buttons, layout(buttons, self.display.length), self.pressed)
        del cr
        self.display.flush()
        self.dirty, self.shown_minute = False, int(time.time() // 60)

    # --- input -------------------------------------------------------------------------
    def handle(self, events):
        for kind, etype, code, value in events:
            if kind == "kbd":
                if etype == hw.EV_KEY and code == hw.KEYS["FN"] and value in (0, 1):
                    self.set_layer("fn" if value else "control")
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
        elif self.was_down and not self.touch_down:
            self.release()
            self.ignore_touch = False
        self.was_down = self.touch_down

    def press(self):
        if self.ignore_touch or self.display is None:
            return
        buttons = self.cfg[self.layer]
        i = hit(layout(buttons, self.display.length), self.bar_x())
        if i is None:
            return
        self.held = buttons[i]["codes"]
        if self.held:
            self.keyboard.send(self.held, 1)
        self.pressed, self.dirty = i, True

    def release(self):
        if self.held:
            self.keyboard.send(self.held, 0)
        self.held = []
        if self.pressed is not None:
            self.pressed, self.dirty = None, True

    def set_layer(self, layer):
        if layer != self.layer:
            self.release()  # never leave a key of the old layer stuck down
            self.layer, self.dirty = layer, True

    # --- idle cat ----------------------------------------------------------------------
    def run_cat(self, stop_after=None):
        """Cat scenes until input arrives; returns the waking events."""
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
                events = self.inputs.read(ms / 1000)
                if events:
                    return events
            if stop_after and time.monotonic() - started > stop_after:
                return []
            events = self.inputs.read(rng.uniform(2, 6))
            if events:
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
        idle, last_scan = self.cfg.get("idle_seconds", 60), 0.0
        while True:
            try:
                now = time.monotonic()
                if now - last_scan > 5:
                    self.inputs.refresh()
                    last_scan = now
                if self.shown_minute != int(time.time() // 60):
                    self.dirty = True  # clock and battery
                if self.dirty:
                    self.render()
                idle_left = idle - (now - self.last_input)
                if idle_left <= 0 and not self.touch_down:
                    self.wake(self.run_cat())
                    continue
                events = self.inputs.read(min(60 - time.time() % 60 + 0.05, idle_left))
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
    assert hw.key_code("KEY_brightnessdown") == 224
    # left end, top edge -> buffer (across, 0); a point 10 px in, 5 px down -> (55, 10)
    assert hw.bar_to_buffer(0, 0, 60, 2008) == (60, 0)
    assert hw.bar_to_buffer(10, 5, 60, 2008) == (55, 10)
    assert hw.bar_to_buffer(10, 5, 60, 2008, flip_along=True) == (55, 1998)
    cfg = load_config(config)
    for layer in ("control", "fn"):
        rects = layout(cfg[layer], 2008)
        assert abs(rects[-1][1] - 2008) < 1e-6 and rects[0][0] == 0, layer
        assert all(abs(b[0] - a[1] - SPACING) < 1e-6 for a, b in zip(rects, rects[1:]))
        assert [hit(rects, (x0 + x1) / 2) for x0, x1 in rects] == list(range(len(rects)))
        assert hit(rects, rects[0][1] + SPACING / 2 - 1) == 0 and hit(rects, rects[0][1] + SPACING / 2 + 1) == 1
    assert cfg["control"][3]["codes"] == [k["LEFTMETA"], k["A"]]
    art.self_test()
    top = (60 - art.H * art.SCALE) // 2
    across = 60 - 1 - (top + 15 * art.SCALE)  # nose cell (row 15, col 12)
    pink = bytes(reversed(art.PALETTE["p"]))
    strips = build_strips(art.draw(), 60, False)
    assert strips[12 * art.SCALE][across * 4:across * 4 + 3] == pink
    assert build_strips(art.draw(), 60, True)[(art.W - 1 - 12) * art.SCALE][across * 4:across * 4 + 3] == pink
    assert not any(any(s) for s in build_strips(art.draw(**art.SINK[-1][0]), 60, False))
    print("self-test OK")


def render_test(config):
    """Draw both layers off-screen with the real matrix (needs pycairo; run on the Mac)."""
    import cairo
    import tb_ui
    cfg = load_config(config)
    across, length = 60, 2008
    for layer in ("control", "fn"):
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, across, length)
        cr = cairo.Context(surface)
        cr.set_matrix(cairo.Matrix(0, 1, -1, 0, across, 0))
        rects = layout(cfg[layer], length)
        tb_ui.draw_buttons(cr, cfg[layer], rects, pressed=0)
        surface.flush()
        data, stride = surface.get_data(), surface.get_stride()
        for i, (x0, x1) in enumerate(rects):  # button background just below the top edge
            bx, by = hw.bar_to_buffer(int(x0 + 10), 6, across, length)
            px = data[by * stride + (bx - 1) * 4 + 2]  # red channel
            want = round(255 * (tb_ui.BUTTON_PRESSED if i == 0 else tb_ui.BUTTON))
            assert abs(px - want) <= 2, (layer, i, px, want)
        gap = hw.bar_to_buffer(int(rects[0][1] + SPACING / 2), 30, across, length)
        assert data[gap[1] * stride + (gap[0] - 1) * 4 + 2] == 0, "gap between buttons is black"
    print("render-test OK")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=CONFIG)
    p.add_argument("--flip-along", action="store_true", help="panel's left end is buffer row 2008")
    p.add_argument("--touch-flip", action="store_true", help="touch x runs right to left")
    p.add_argument("--cat-demo", type=float, metavar="SECONDS", help="show the cat now, then exit")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--render-test", action="store_true")
    args = p.parse_args()
    if not os.path.exists(args.config):  # running from a checkout
        args.config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "touchbar.toml")
    if args.self_test:
        return self_test(args.config)
    if args.render_test:
        return render_test(args.config)

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
