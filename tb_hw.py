"""Hardware access for the T2 Touch Bar: appletbdrm display, evdev input, uinput keyboard.

Standard library only (K-006), except Display.context() which needs pycairo (present on the Mac, not
on the dev machine, so it is imported lazily and the rest stays testable anywhere).
"""
import ctypes
import fcntl
import glob
import mmap
import os
import struct


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


def _ioctl(fd, req, fmt, *values):
    buf = bytearray(struct.pack(fmt, *values))
    fcntl.ioctl(fd, req, buf, True)
    return struct.unpack(fmt, buf)


def find_card():
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        if os.path.basename(os.path.realpath(card + "/device/driver")) == "appletbdrm":
            return "/dev/dri/" + os.path.basename(card)
    return None


def bar_to_buffer(x, y, across, length, flip_along=False):
    """Map bar coordinates (x along, 0 = left end; y across, 0 = top edge) to the buffer.

    The panel is portrait (across x length) and mounted rotated by +90 degrees: buffer x runs
    from the bar's bottom edge to its top, buffer y from its left end to its right. Measured
    on MacBookPro16,2: the unrotated mapping drew the cat upside down (buffer x = 0 is the
    bottom edge). flip_along covers a panel whose left end is buffer y = length instead.
    """
    return across - y, (length - x) if flip_along else x


class Display:
    """Dumb buffer on the appletbdrm card; draw with context() in bar coordinates."""

    def __init__(self, flip_along=False):
        path = find_card()
        if not path:
            raise FileNotFoundError("no appletbdrm card")
        self.flip_along = flip_along
        self.fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        self.fb_id = self.handle = 0
        self.map = self.surface = None
        try:
            fcntl.ioctl(self.fd, SET_MASTER)
        except OSError:
            pass  # the first opener of a card is master already
        conn_id, crtc_id, mode = self._pick_output()
        info = struct.unpack(MODEINFO, mode)
        self.across, self.length = info[1], info[6]  # hdisplay 60, vdisplay 2008
        _, _, _, _, self.handle, self.pitch, size = _ioctl(
            self.fd, CREATE_DUMB_IOC, CREATE_DUMB, self.length, self.across, 32, 0, 0, 0, 0)
        self.fb_id = _ioctl(self.fd, ADDFB, FB_CMD, 0, self.across, self.length, self.pitch,
                            32, 24, self.handle)[0]
        offset = _ioctl(self.fd, MAP_DUMB_IOC, MAP_DUMB, self.handle, 0, 0)[2]
        self.map = mmap.mmap(self.fd, size, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)
        self.map[:] = bytes(size)
        conns = (ctypes.c_uint32 * 1)(conn_id)
        _ioctl(self.fd, SETCRTC, CRTC, ctypes.addressof(conns), 1, crtc_id, self.fb_id,
               0, 0, 0, 1, *info)
        self.flush()

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

    def context(self):
        """A cairo context drawing straight into the scanout buffer, in bar coordinates."""
        import cairo
        if self.surface is None:
            self.surface = cairo.ImageSurface.create_for_data(
                self.map, cairo.FORMAT_RGB24, self.across, self.length, self.pitch)
        cr = cairo.Context(self.surface)
        # x' = xx*x + xy*y + x0, y' = yx*x + yy*y + y0 -- the same map as bar_to_buffer()
        if self.flip_along:
            cr.set_matrix(cairo.Matrix(0, -1, -1, 0, self.across, self.length))
        else:
            cr.set_matrix(cairo.Matrix(0, 1, -1, 0, self.across, 0))
        return cr

    def write_col(self, col, data):
        """Raw XRGB row for one bar column (used by the cat, which pre-renders strips)."""
        if self.flip_along:
            col = self.length - 1 - col
        start = col * self.pitch
        self.map[start:start + len(data)] = data

    def flush(self, x0=0, x1=None):
        """Send bar columns [x0, x1) to the panel (appletbdrm only transfers dirty rects)."""
        x1 = self.length if x1 is None else x1
        if self.surface is not None:
            self.surface.flush()
            self.surface.mark_dirty()
        x0, x1 = max(x0, 0), min(x1, self.length)
        if self.flip_along:
            x0, x1 = self.length - x1, self.length - x0
        clip = (ctypes.c_uint16 * 4)(0, x0, self.across, x1)
        _ioctl(self.fd, DIRTYFB, FB_DIRTY, self.fb_id, 0, 0, 1, ctypes.addressof(clip))

    def close(self):
        self.surface = None
        for req, arg in ((RMFB, self.fb_id), (DESTROY_DUMB, self.handle)):
            if arg:
                try:
                    fcntl.ioctl(self.fd, req, bytearray(struct.pack("<I", arg)), True)
                except OSError:
                    pass
        if self.map:
            try:
                self.map.close()
            except (OSError, BufferError):
                pass
        try:
            fcntl.ioctl(self.fd, DROP_MASTER)
        except OSError:
            pass
        os.close(self.fd)


def set_bar_brightness(level):
    for path in glob.glob("/sys/class/backlight/appletb_backlight/brightness"):
        with open(path, "w") as f:
            f.write(str(level))


# --- sysfs knobs the sliders and quick settings drive (root) ----------------------------
def screen_backlight():
    """The main display's backlight dir (intel_backlight, gmux_backlight...), not the bar's."""
    dirs = [d for d in sorted(glob.glob("/sys/class/backlight/*")) if "appletb" not in d]
    return dirs[0] if dirs else None


def keyboard_backlight():
    dirs = sorted(glob.glob("/sys/class/leds/*kbd_backlight*"))
    return dirs[0] if dirs else None


def read_level(path):
    """Brightness as 0.0-1.0, or None when the device is missing."""
    try:
        with open(path + "/brightness") as cur, open(path + "/max_brightness") as top:
            return int(cur.read()) / max(int(top.read()), 1)
    except (OSError, TypeError, ValueError):
        return None


def write_level(path, value, floor=0.0):
    with open(path + "/max_brightness") as f:
        top = int(f.read())
    with open(path + "/brightness", "w") as f:
        f.write(str(round(max(floor, min(1.0, value)) * top)))


def rfkill_enabled(kind):
    """Radio on? kind is the rfkill type ('wlan', 'bluetooth'); None if there is no such radio."""
    states = []
    for d in glob.glob("/sys/class/rfkill/rfkill*"):
        try:
            with open(d + "/type") as f:
                if f.read().strip() != kind:
                    continue
            with open(d + "/soft") as s, open(d + "/hard") as h:
                states.append(s.read().strip() == "0" and h.read().strip() == "0")
        except OSError:
            pass
    return any(states) if states else None


def rfkill_set(kind, on):
    for d in glob.glob("/sys/class/rfkill/rfkill*"):
        with open(d + "/type") as f:
            if f.read().strip() == kind:
                with open(d + "/soft", "w") as s:
                    s.write("0" if on else "1")


# --- evdev / uinput (include/uapi/linux/input.h, uinput.h) ------------------------------
EVENT = struct.Struct("llHHi")      # struct input_event on x86_64 (24 bytes)
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT = 0
ABS_X = 0x00
BTN_TOUCH = 0x14A
EVIOCGRAB = 0x40044590              # _IOW('E', 0x90, int)
UI_SET_EVBIT = 0x40045564           # _IOW('U', 100, int)
UI_SET_KEYBIT = 0x40045565          # _IOW('U', 101, int)
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UINPUT_USER_DEV = "<80sHHHHI256i"   # struct uinput_user_dev (1116 bytes)
BUS_VIRTUAL = 0x06

_ROWS = ((16, "QWERTYUIOP"), (30, "ASDFGHJKL"), (44, "ZXCVBNM"))
KEYS = {
    "ESC": 1, "MINUS": 12, "EQUAL": 13, "BACKSPACE": 14, "TAB": 15, "ENTER": 28,
    "LEFTCTRL": 29, "LEFTSHIFT": 42, "RIGHTSHIFT": 54, "LEFTALT": 56, "SPACE": 57,
    "RIGHTALT": 100, "SYSRQ": 99, "HOME": 102, "UP": 103, "PAGEUP": 104, "LEFT": 105,
    "RIGHT": 106, "END": 107, "DOWN": 108, "PAGEDOWN": 109, "DELETE": 111, "MUTE": 113,
    "VOLUMEDOWN": 114, "VOLUMEUP": 115, "LEFTMETA": 125, "NEXTSONG": 163, "PLAYPAUSE": 164,
    "PREVIOUSSONG": 165, "SEARCH": 217, "BRIGHTNESSDOWN": 224, "BRIGHTNESSUP": 225,
    "KBDILLUMDOWN": 229, "KBDILLUMUP": 230, "MICMUTE": 248, "FN": 464,
    "LEFTBRACE": 26, "RIGHTBRACE": 27, "SEMICOLON": 39, "APOSTROPHE": 40, "GRAVE": 41,
    "BACKSLASH": 43, "COMMA": 51, "DOT": 52, "SLASH": 53, "CAPSLOCK": 58, "RIGHTCTRL": 97,
    "INSERT": 110, "RIGHTMETA": 126,
    **{str(i % 10): 1 + i for i in range(1, 11)},                       # 1..9, 0
    **{f"F{i}": 58 + i for i in range(1, 11)}, "F11": 87, "F12": 88,
    **{f"F{i}": 170 + i for i in range(13, 25)},                        # F13 = 183
    **{ch: base + i for base, row in _ROWS for i, ch in enumerate(row)},
}


def key_code(name):
    return KEYS[name.upper().removeprefix("KEY_")]


class Keyboard:
    """Virtual keyboard the Touch Bar types through (replaces tiny-dfr's uinput device)."""

    NAME = "Touch Bar Virtual Keyboard"

    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_SYN)
        # key codes only: 0x100-0x15f and 0x2c0+ are BTN_* and would make it look like a mouse
        for code in [*range(1, 0x100), *range(0x160, 0x2c0)]:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        os.write(self.fd, struct.pack(UINPUT_USER_DEV, self.NAME.encode(), BUS_VIRTUAL,
                                      0x05AC, 0x7400, 1, 0, *([0] * 256)))
        fcntl.ioctl(self.fd, UI_DEV_CREATE)

    def send(self, codes, value):
        """Press (1) or release (0) a key combo; releases go in reverse order."""
        seq = codes if value else list(reversed(codes))
        os.write(self.fd, b"".join(EVENT.pack(0, 0, EV_KEY, c, value) for c in seq)
                 + EVENT.pack(0, 0, EV_SYN, SYN_REPORT, 0))

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


def input_devices():
    """{device name: [/dev/input/eventN, ...]} from /proc/bus/input/devices."""
    found, name = {}, ""
    with open("/proc/bus/input/devices") as f:
        for line in f:
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("H: Handlers="):
                found.setdefault(name, []).extend(
                    "/dev/input/" + h for h in line.split("=", 1)[1].split() if h.startswith("event"))
    return found
