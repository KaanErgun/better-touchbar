#!/usr/bin/env python3
"""Touch Bar cat: a chibi cat pops up on the T2 Touch Bar while the machine is idle.

Independent of tiny-dfr: when every watched input has been quiet for --idle seconds, the
daemon stops tiny-dfr, becomes DRM master of the appletbdrm card and plays scenes: the cat
rises at a random spot, does one of six gestures (cat_art.GESTURES), sinks, and reappears
elsewhere a few seconds later.
Any key press, trackpad or Touch Bar touch hands the bar straight back to tiny-dfr.
Standard library only (raw DRM ioctls + mmap'd dumb buffer), runs as root under systemd.
"""
import argparse
import ctypes
import fcntl
import glob
import mmap
import os
import random
import select
import signal
import struct
import subprocess
import sys
import time

import cat_art as art

# --- DRM uapi (include/uapi/drm/drm.h, drm_mode.h); x86_64, little-endian ---------------
def _iowr(nr, size):
    return 0xC0000000 | (size << 16) | (ord("d") << 8) | nr

MODEINFO = "<I5H5HIII32s"            # struct drm_mode_modeinfo (68 bytes)
CARD_RES = "<4Q8I"                   # struct drm_mode_card_res (64)
GET_CONNECTOR = "<4Q3I4I4II"         # struct drm_mode_get_connector (80)
GET_ENCODER = "<5I"                  # struct drm_mode_get_encoder (20)
CRTC = "<QIIIIIII" + MODEINFO[1:]    # struct drm_mode_crtc (104)
CREATE_DUMB = "<6IQ"                 # struct drm_mode_create_dumb (32)
MAP_DUMB = "<IIQ"                    # struct drm_mode_map_dumb (16)
FB_CMD = "<7I"                       # struct drm_mode_fb_cmd (28)
FB_DIRTY = "<4IQ"                    # struct drm_mode_fb_dirty_cmd (24)
CLIP = "<4H"                         # struct drm_clip_rect (8)

SET_MASTER = (ord("d") << 8) | 0x1E
DROP_MASTER = (ord("d") << 8) | 0x1F
GETRESOURCES = _iowr(0xA0, struct.calcsize(CARD_RES))
SETCRTC = _iowr(0xA2, struct.calcsize(CRTC))
GETENCODER = _iowr(0xA6, struct.calcsize(GET_ENCODER))
GETCONNECTOR = _iowr(0xA7, struct.calcsize(GET_CONNECTOR))
ADDFB = _iowr(0xAE, struct.calcsize(FB_CMD))
RMFB = _iowr(0xAF, 4)
DIRTYFB = _iowr(0xB1, struct.calcsize(FB_DIRTY))
CREATE_DUMB_IOC = _iowr(0xB2, struct.calcsize(CREATE_DUMB))
MAP_DUMB_IOC = _iowr(0xB3, struct.calcsize(MAP_DUMB))
DESTROY_DUMB = _iowr(0xB4, 4)

# --- Rendering --------------------------------------------------------------------------
WIDTH = art.W * art.SCALE  # bar columns one cat scene occupies


def build_strips(rows, bar_height, flip_across, mirror):
    """Pre-render a pose (cat_art.draw rows) as one XRGB8888 row per bar column.

    The appletbdrm panel is portrait (bar_height x length): a buffer row is one column of
    the physical bar, so drawing the cat at bar position x means writing rows x..x+WIDTH.
    """
    top = (bar_height - art.H * art.SCALE) // 2
    strips = []
    for col in range(WIDTH):
        src_col = col // art.SCALE
        if mirror:
            src_col = art.W - 1 - src_col
        row = bytearray(bar_height * 4)
        for y in range(art.H * art.SCALE):
            ch = rows[y // art.SCALE][src_col]
            if ch == ".":
                continue
            # Buffer column 0 is the bottom edge of the bar on MacBookPro16,2 (seen on
            # hardware: the unflipped mapping drew the cat upside down).
            across = top + y if flip_across else bar_height - 1 - (top + y)
            r, g, b = art.PALETTE[ch]
            row[across * 4:across * 4 + 4] = bytes((b, g, r, 0))  # XRGB8888, little-endian
        strips.append(bytes(row))
    return strips


# --- DRM plumbing -----------------------------------------------------------------------
def find_card():
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        if os.path.basename(os.path.realpath(card + "/device/driver")) == "appletbdrm":
            return "/dev/dri/" + os.path.basename(card)
    return None


def _ioctl(fd, req, fmt, *values):
    buf = bytearray(struct.pack(fmt, *values))
    fcntl.ioctl(fd, req, buf, True)
    return struct.unpack(fmt, buf)


class TouchBarDisplay:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        self.fb_id = self.handle = 0
        self.map = None
        try:
            fcntl.ioctl(self.fd, SET_MASTER)
        except OSError:
            pass  # the first opener of a card is master already
        conn_id, crtc_id, mode = self._pick_output()
        self.height_across = struct.unpack(MODEINFO, mode)[1]   # hdisplay: 60
        self.length = struct.unpack(MODEINFO, mode)[6]          # vdisplay: 2008
        h, w = self.length, self.height_across
        _, _, _, _, self.handle, self.pitch, size = _ioctl(
            self.fd, CREATE_DUMB_IOC, CREATE_DUMB, h, w, 32, 0, 0, 0, 0)
        self.fb_id = _ioctl(self.fd, ADDFB, FB_CMD, 0, w, h, self.pitch, 32, 24, self.handle)[0]
        offset = _ioctl(self.fd, MAP_DUMB_IOC, MAP_DUMB, self.handle, 0, 0)[2]
        self.map = mmap.mmap(self.fd, size, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)
        self.map[:] = bytes(size)
        conns = (ctypes.c_uint32 * 1)(conn_id)
        _ioctl(self.fd, SETCRTC, CRTC, ctypes.addressof(conns), 1, crtc_id, self.fb_id,
               0, 0, 0, 1, *struct.unpack(MODEINFO, mode))
        self.flush(0, self.length)

    def _pick_output(self):
        counts = _ioctl(self.fd, GETRESOURCES, CARD_RES, *([0] * 12))
        n_fb, n_crtc, n_conn, n_enc = counts[4:8]
        arrays = [(ctypes.c_uint32 * max(n, 1))() for n in (n_fb, n_crtc, n_conn, n_enc)]
        _ioctl(self.fd, GETRESOURCES, CARD_RES, *[ctypes.addressof(a) for a in arrays],
               n_fb, n_crtc, n_conn, n_enc, 0, 0, 0, 0)
        crtcs, connectors = list(arrays[1][:n_crtc]), list(arrays[2][:n_conn])
        for conn_id in connectors:
            c = _ioctl(self.fd, GETCONNECTOR, GET_CONNECTOR, 0, 0, 0, 0, 0, 0, 0,
                       0, conn_id, 0, 0, 0, 0, 0, 0, 0)
            n_modes, n_props, n_encs = c[4:7]
            if not n_modes:
                continue
            modes = ctypes.create_string_buffer(n_modes * struct.calcsize(MODEINFO))
            encs = (ctypes.c_uint32 * max(n_encs, 1))()
            props = (ctypes.c_uint32 * max(n_props, 1))()
            vals = (ctypes.c_uint64 * max(n_props, 1))()
            c = _ioctl(self.fd, GETCONNECTOR, GET_CONNECTOR, ctypes.addressof(encs),
                       ctypes.addressof(modes), ctypes.addressof(props), ctypes.addressof(vals),
                       n_modes, n_props, n_encs, 0, conn_id, 0, 0, 0, 0, 0, 0, 0)
            crtc_id = 0
            if c[7]:  # current encoder -> its crtc
                crtc_id = _ioctl(self.fd, GETENCODER, GET_ENCODER, c[7], 0, 0, 0, 0)[2]
            return conn_id, crtc_id or crtcs[0], modes.raw[:struct.calcsize(MODEINFO)]
        raise RuntimeError("appletbdrm card has no connector with a mode")

    def flush(self, first_col, last_col):
        """Mark bar columns [first_col, last_col) dirty so appletbdrm sends them over USB."""
        first_col, last_col = max(first_col, 0), min(last_col, self.length)
        clip = (ctypes.c_uint16 * 4)(0, first_col, self.height_across, last_col)
        _ioctl(self.fd, DIRTYFB, FB_DIRTY, self.fb_id, 0, 0, 1, ctypes.addressof(clip))

    def write_col(self, col, data):
        start = col * self.pitch
        self.map[start:start + len(data)] = data

    def close(self):
        for req, arg in ((RMFB, self.fb_id), (DESTROY_DUMB, self.handle)):
            if arg:
                try:
                    fcntl.ioctl(self.fd, req, bytearray(struct.pack("<I", arg)), True)
                except OSError:
                    pass
        if self.map:
            self.map.close()
        try:
            fcntl.ioctl(self.fd, DROP_MASTER)
        except OSError:
            pass
        os.close(self.fd)


# --- Idle detection ---------------------------------------------------------------------
# tiny-dfr keeps the Touch Bar touchpad to itself while running; its button presses surface on
# its uinput device instead, so that one is watched too (it disappears while the cat is out).
WATCHED = ("Touch Bar Display Touchpad", "Apple Internal Keyboard / Trackpad",
           "Dynamic Function Row Virtual Input Device")


def find_inputs():
    paths, name = [], ""
    with open("/proc/bus/input/devices") as f:
        for line in f:
            if line.startswith("N: Name="):
                name = line
            elif line.startswith("H: Handlers=") and any(w in name for w in WATCHED):
                paths += ["/dev/input/" + h for h in line.split("=", 1)[1].split()
                          if h.startswith("event")]
    return paths


class InputWatch:
    def __init__(self):
        self.fds = {}
        self.last_source = ""

    def refresh(self):
        wanted = set(find_inputs())
        for path in list(self.fds):
            if path not in wanted:
                os.close(self.fds.pop(path))
        for path in wanted - set(self.fds):
            try:
                self.fds[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                pass

    def _drain(self, fds):
        """Read pending events; True only if real event data arrived."""
        got = False
        for fd in fds:
            try:
                while os.read(fd, 4096):
                    got = True
                    self.last_source = next((p for p, f in self.fds.items() if f == fd), "?")
            except BlockingIOError:
                pass
            except OSError:  # device went away (tiny-dfr's uinput, Touch Bar re-enumeration)
                self.fds = {p: f for p, f in self.fds.items() if f != fd}
                os.close(fd)
        return got

    def drain(self):
        self._drain(list(self.fds.values()))

    def wait(self, timeout):
        """Return True if any watched device produced events within timeout seconds."""
        if not self.fds:
            time.sleep(timeout)
            return False
        ready, _, _ = select.select(list(self.fds.values()), [], [], timeout)
        return self._drain(ready)


# --- Main loop --------------------------------------------------------------------------
def systemctl(action):
    subprocess.run(["systemctl", action, "tiny-dfr.service"], check=False)


def set_bar_brightness(level):
    for path in glob.glob("/sys/class/backlight/appletb_backlight/brightness"):
        with open(path, "w") as f:
            f.write(str(level))


def run_cat(args, watch, stop_after=None):
    """Play scenes until input arrives (or stop_after seconds pass). Returns on any error."""
    systemctl("stop")
    watch.refresh()  # tiny-dfr's uinput device is gone now
    watch.drain()    # drop whatever queued up while tiny-dfr shut down
    display = None
    try:
        card = find_card()
        if not card:
            print("no appletbdrm card, skipping cat mode", flush=True)
            return
        display = TouchBarDisplay(card)
        set_bar_brightness(args.brightness)
        rng, cache, last = random.Random(), {}, None
        gestures = [args.only] if args.only else list(art.GESTURES)
        started = time.monotonic()
        print("cat mode on", flush=True)
        while True:
            x = rng.randrange(0, display.length - WIDTH)
            mirror = rng.random() < 0.5
            name = rng.choice([g for g in gestures if g != last] or gestures)
            last = name
            print(f"gesture {name} at {x}", flush=True)
            for kw, ms in art.RISE + art.GESTURES[name] + art.SINK:
                key = (art.draw(**kw), mirror)
                if key not in cache:
                    cache[key] = build_strips(key[0], display.height_across,
                                              args.flip_across, mirror)
                for i, strip in enumerate(cache[key]):
                    display.write_col(x + i, strip)
                display.flush(x, x + WIDTH)
                if watch.wait(ms / 1000):
                    print(f"woken by {watch.last_source}", flush=True)
                    return
            # the last SINK pose is empty, so the bar is dark again here
            if stop_after and time.monotonic() - started > stop_after:
                return
            if watch.wait(rng.uniform(args.pause_min, args.pause_max)):
                print(f"woken by {watch.last_source}", flush=True)
                return
    except OSError as e:
        print(f"cat mode aborted: {e}", flush=True)
        # The card vanished (resume re-registers it). Starting tiny-dfr mid-churn lets its BindsTo=
        # stop it again with the old device, so wait for udev to settle first.
        subprocess.run(["udevadm", "settle", "--timeout=10"], check=False)
        time.sleep(2)
    finally:
        if display:
            try:
                display.close()
            except OSError:
                pass  # fd of a device that is already gone
        systemctl("start")
        print("cat mode off", flush=True)


def self_test():
    sizes = {MODEINFO: 68, CARD_RES: 64, GET_CONNECTOR: 80, GET_ENCODER: 20, CRTC: 104,
             CREATE_DUMB: 32, MAP_DUMB: 16, FB_CMD: 28, FB_DIRTY: 24, CLIP: 8}
    for fmt, size in sizes.items():
        assert struct.calcsize(fmt) == size, (fmt, struct.calcsize(fmt), size)
    assert DIRTYFB == 0xC01864B1 and CREATE_DUMB_IOC == 0xC02064B2 and SETCRTC == 0xC06864A2
    art.self_test()
    rows = art.draw()
    top = (60 - art.H * art.SCALE) // 2
    across = 60 - 1 - (top + 15 * art.SCALE)  # nose cell (row 15, col 12), default mapping
    pink = bytes(reversed(art.PALETTE["p"]))
    assert build_strips(rows, 60, False, False)[12 * art.SCALE][across * 4:across * 4 + 3] == pink
    across = top + 15 * art.SCALE
    mirrored = build_strips(rows, 60, True, True)
    assert mirrored[(art.W - 1 - 12) * art.SCALE][across * 4:across * 4 + 3] == pink
    sunk = build_strips(art.draw(**art.SINK[-1][0]), 60, False, False)
    assert all(not any(strip) for strip in sunk), "last sink pose must clear the bar"
    print("self-test OK")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--idle", type=float, default=60, help="seconds without input before the cat")
    p.add_argument("--pause-min", type=float, default=2, help="seconds between scenes, min")
    p.add_argument("--pause-max", type=float, default=6, help="seconds between scenes, max")
    p.add_argument("--only", choices=sorted(art.GESTURES), help="play just this gesture")
    p.add_argument("--brightness", type=int, default=1, choices=(1, 2))
    p.add_argument("--flip-across", action="store_true",
                   help="use if the cat is upside down on a different model")
    p.add_argument("--demo", type=float, metavar="SECONDS", help="show the cat now, then exit")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # unwinds run_cat's finally
    watch = InputWatch()
    watch.refresh()
    if args.demo:
        return run_cat(args, watch, stop_after=args.demo)
    last_input, last_scan = time.monotonic(), 0.0
    while True:
        now = time.monotonic()
        if now - last_scan > 5:
            watch.refresh()
            last_scan = now
        if watch.wait(1):
            last_input = time.monotonic()
        elif time.monotonic() - last_input >= args.idle:
            watch.refresh()
            run_cat(args, watch)
            last_input = time.monotonic()


if __name__ == "__main__":
    main()
