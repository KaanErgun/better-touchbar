"""Chibi cat head for the Touch Bar, composed from shapes; gestures are lists of (pose, ms).

The head fills the 60 px bar height and is cut off by the bottom edge, so the cat looks
like it is peeking up into the bar. Everything is generated here (no sprite files): a pose
is a set of keyword arguments to draw(), a gesture is a timed list of poses.
"""
from functools import lru_cache

W, H, SCALE = 26, 20, 3  # cells; 20 * 3 = 60 px = bar height

PALETTE = {  # RGB
    "k": (95, 58, 38),     # outline, warm brown (pure black vanishes on the OLED)
    "o": (245, 150, 50),   # orange fur
    "d": (205, 100, 30),   # tabby marks
    "l": (255, 226, 180),  # cream muzzle
    "w": (250, 250, 250),  # white paws, fangs
    "p": (245, 135, 165),  # pink nose, inner ears
    "b": (255, 150, 150),  # blush
    "i": (120, 195, 85),   # green iris
    "e": (20, 15, 20),     # pupil
    "h": (255, 255, 255),  # eye highlight
    "m": (140, 40, 55),    # mouth inside
    "t": (240, 105, 130),  # tongue
    "y": (205, 205, 205),  # whiskers, z's
    "r": (255, 80, 120),   # heart
}


def _ellipse(cx, cy, rx, ry):
    return lambda x, y: ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1


def _tri(a, b, c):
    def inside(x, y):
        p = (x + .5, y + .5)
        d = lambda u, v, w: (u[0] - w[0]) * (v[1] - w[1]) - (v[0] - w[0]) * (u[1] - w[1])
        s = (d(p, a, b), d(p, b, c), d(p, c, a))
        return not (min(s) < 0 < max(s))
    return inside


def _mirror_pt(p):
    return (W - p[0], p[1])


EARS = {  # (outer tip, inner-ear tip) for the left ear; the right ear is mirrored
    "up": ((4.0, 0.3), (5.1, 2.6)),
    "back": ((0.2, 5.0), (2.4, 5.6)),     # airplane ears (yawn)
    "twitch": ((4.0, 0.3), (5.1, 2.6)),   # right ear flicks, see draw()
}
HEAD = _ellipse(13.0, 12.8, 11.2, 8.8)
EYES = ((8.3, 12.0), (17.7, 12.0))
MUZZLE = _ellipse(13.0, 16.9, 5.4, 3.2)
BLUSH = (_ellipse(5.1, 15.6, 1.9, 0.9), _ellipse(20.9, 15.6, 1.9, 0.9))
HEART = [".r.r.", "rrrrr", ".rrr.", "..r.."]
ZZ = {"z": ["yyy", ".y.", "yyy"], "Z": ["yyyy", "..y.", ".y..", "yyyy"]}


def _ear_shapes(state):
    tip, inner_tip = EARS[state]
    left = _tri((2.4, 9.2), tip, (10.8, 4.4))
    left_in = _tri((4.6, 7.4), inner_tip, (8.8, 5.0))
    rtip = (23.2, 1.6) if state == "twitch" else _mirror_pt(tip)
    rin = (21.6, 3.4) if state == "twitch" else _mirror_pt(inner_tip)
    right = _tri((23.6, 9.2), rtip, (15.2, 4.4))
    right_in = _tri((21.4, 7.4), rin, (17.2, 5.0))
    return (left, right), (left_in, right_in)


def _line(g, pts, ch):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * 3) + 1
        for i in range(n + 1):
            x, y = x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n
            _put(g, int(x), int(y), ch)


def _put(g, x, y, ch):
    if 0 <= x < W and 0 <= y < H:
        g[y][x] = ch


def _stamp(g, pattern, x0, y0):
    for dy, row in enumerate(pattern):
        for dx, ch in enumerate(row):
            if ch != ".":
                _put(g, x0 + dx, y0 + dy, ch)


def _blob(g, mask, fill, outline="k"):
    """Draw a filled shape with its own outline (edges against anything outside the shape)."""
    for y in range(H):
        for x in range(W):
            if mask(x, y):
                edge = any(not mask(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                g[y][x] = outline if edge else fill


def _eye(g, cx, cy, state, look, pupil):
    if state in ("open", "half"):
        _blob(g, _ellipse(cx, cy, 2.6, 3.0), "i")
        rx = {"big": 1.6, "huge": 2.0, "slit": 0.55}[pupil]
        px, py = cx + look[0] * 0.9, cy + look[1] * 0.6
        pup = _ellipse(px, py, rx, 2.3)
        iris = _ellipse(cx, cy, 2.6, 3.0)
        for y in range(H):
            for x in range(W):
                if pup(x, y) and iris(x, y) and g[y][x] == "i":
                    g[y][x] = "e"
        _put(g, int(cx - 1.2 + look[0] * 0.5), int(cy - 1.6), "h")
        _put(g, int(cx - 0.2 + look[0] * 0.5), int(cy - 1.6), "h")
        _put(g, int(cx + 0.9 + look[0] * 0.5), int(cy + 1.1), "h")
        if state == "half":  # upper lid down to the middle
            for y in range(int(cy - 3.2), int(cy)):
                for x in range(int(cx - 3), int(cx + 3) + 1):
                    if _ellipse(cx, cy, 2.7, 3.1)(x, y):
                        _put(g, x, y, "o")
            _line(g, [(cx - 2.6, cy), (cx + 2.4, cy)], "k")
    elif state == "closed":  # relaxed, curving down: u
        _line(g, [(cx - 2.4, cy - 0.2), (cx - 1, cy + 0.8), (cx + 1, cy + 0.8), (cx + 2.4, cy - 0.2)], "k")
    elif state == "happy":   # ^ ^
        _line(g, [(cx - 2.4, cy + 0.8), (cx, cy - 1.2), (cx + 2.4, cy + 0.8)], "k")
    elif state == "squeeze":  # > <, pointing at the nose
        s = 1 if cx < W / 2 else -1
        _line(g, [(cx - 2 * s, cy - 1.6), (cx + 1.2 * s, cy), (cx - 2 * s, cy + 1.6)], "k")


def _mouth(g, state):
    if state == "yawn":
        _blob(g, _ellipse(13.0, 18.6, 3.3, 3.0), "m")
        for y in range(18, H):
            for x in range(11, 15):
                if g[y][x] == "m" and y >= 19:
                    g[y][x] = "t"
        _put(g, 11, 17, "w"); _put(g, 14, 17, "w")   # fangs
    elif state == "open_small":
        _blob(g, _ellipse(13.0, 17.6, 1.7, 1.4), "m")
        _put(g, 12, 18, "t"); _put(g, 13, 18, "t")
    else:  # neutral / tongue: the omega mouth
        for x, y in ((12, 16), (13, 16), (11, 17), (14, 17), (10, 16), (15, 16)):
            _put(g, x, y, "k")
        if state == "tongue":
            for x, y in ((12, 17), (13, 17), (12, 18), (13, 18)):
                _put(g, x, y, "t")
            _put(g, 11, 18, "k"); _put(g, 14, 18, "k"); _put(g, 12, 19, "k"); _put(g, 13, 19, "k")
    # nose on top
    for x, y in ((11, 14), (12, 14), (13, 14), (14, 14), (12, 15), (13, 15)):
        _put(g, x, y, "p")


PAW = [  # 9 wide; toe beans make it read as a paw even at 3 px per cell
    "..kkkkk..",
    ".kwwwwwk.",
    "kwpwpwpwk",
    "kwwwwwwwk",
    "kwwpppwwk",
    "kwwpppwwk",
    ".kwwwwwk.",
]


def _paw(g, x0, top):
    """A raised front paw: white mitten at (x0, top) on an arm reaching up from below."""
    for y in range(top + len(PAW), H):
        for dx in range(1, 8):
            _put(g, x0 + dx, y, "k" if dx in (1, 7) else "o")
    _stamp(g, PAW, x0, top)


@lru_cache(maxsize=None)
def draw(eyes="open", look=(0, 0), pupil="big", mouth="neutral", ears="up", paws=(), dy=0,
         extras=()):
    """Return the pose as H strings of W palette chars ('.' = transparent)."""
    g = [["." for _ in range(W)] for _ in range(H)]
    (ear_l, ear_r), (in_l, in_r) = _ear_shapes(ears)
    head = lambda x, y: HEAD(x, y) or ear_l(x, y) or ear_r(x, y)
    # the head continues below the bar, so the bottom edge gets no outline
    _blob(g, lambda x, y: head(x, min(y, H - 1)), "o")
    for y in range(H):
        for x in range(W):
            if g[y][x] != "o":
                continue
            if in_l(x, y) or in_r(x, y):
                g[y][x] = "p"
            elif MUZZLE(x, y):
                g[y][x] = "l"
            elif any(b(x, y) for b in BLUSH):
                g[y][x] = "b"
    for x, y in ((12, 5), (13, 5), (12, 6), (13, 6), (9, 6), (9, 7), (16, 6), (16, 7)):
        if g[y][x] == "o":
            g[y][x] = "d"
    for side in (1, -1):  # whiskers
        x0 = 3.2 if side > 0 else W - 3.2
        _line(g, [(x0, 15.6), (x0 - 3.4 * side, 14.8)], "y")
        _line(g, [(x0, 16.8), (x0 - 3.4 * side, 17.4)], "y")
    for cx, cy in EYES:
        _eye(g, cx, cy, eyes, look, pupil)
    _mouth(g, mouth)
    for x0, top in paws:
        _paw(g, x0, top)
    for kind, x, y in extras:
        _stamp(g, HEART if kind == "heart" else ZZ[kind], x, y)
    if dy:
        g = [["."] * W for _ in range(dy)] + g[:H - dy]
    return tuple("".join(r) for r in g)


def pose(**kw):
    return kw


RISE = [(pose(dy=d), 70) for d in (17, 13, 9, 5, 2, 0)]
SINK = [(pose(dy=d), 70) for d in (2, 5, 9, 13, 17, 20)]

GESTURES = {
    "pati_yalama": [
        (pose(), 500),
        (pose(paws=((3, 19),)), 110),
        (pose(paws=((3, 16),), eyes="happy"), 110),
        *[(pose(paws=((3, 14),), eyes="happy", mouth="tongue"), 260),
          (pose(paws=((3, 13),), eyes="happy"), 260)] * 4,
        (pose(paws=((3, 16),), eyes="happy"), 130),
        (pose(), 700),
    ],
    "dik_dik_bakma": [
        (pose(), 400),
        (pose(look=(1, 0)), 300),
        (pose(look=(1, 0), pupil="slit"), 1800),
        (pose(look=(1, 0), pupil="slit", ears="twitch"), 180),
        (pose(look=(1, 0), pupil="slit"), 900),
        (pose(look=(-1, 0), pupil="slit"), 1500),
        (pose(pupil="huge"), 900),
        (pose(), 400),
    ],
    "yavas_goz_kirpma": [
        (pose(), 700), (pose(eyes="half"), 220), (pose(eyes="closed"), 850),
        (pose(eyes="half"), 220), (pose(), 400),
        (pose(extras=(("heart", 20, 4),)), 280), (pose(extras=(("heart", 20, 2),)), 280),
        (pose(extras=(("heart", 20, 0),)), 450), (pose(), 500),
    ],
    "esneme": [
        (pose(), 400), (pose(eyes="closed", mouth="open_small"), 200),
        (pose(eyes="squeeze", mouth="yawn", ears="back"), 1100),
        (pose(eyes="squeeze", mouth="open_small", ears="back"), 200),
        (pose(eyes="closed", mouth="tongue"), 300), (pose(eyes="half"), 300), (pose(), 500),
    ],
    "yogurma": [
        (pose(eyes="happy", paws=((0, 18), (17, 18))), 250),
        *[(pose(eyes="happy", paws=((0, 15), (17, 18))), 300),
          (pose(eyes="happy", paws=((0, 18), (17, 15))), 300)] * 5,
        (pose(eyes="happy"), 400), (pose(), 400),
    ],
    "uyuklama": [
        (pose(), 500), (pose(eyes="half"), 700), (pose(eyes="closed", dy=1), 700),
        (pose(eyes="closed", dy=1, extras=(("z", 20, 3),)), 600),
        (pose(eyes="closed", dy=2, extras=(("z", 20, 3), ("Z", 22, 0))), 900),
        (pose(eyes="closed", dy=2, extras=(("Z", 22, 0),)), 600),
        (pose(pupil="huge"), 600),  # startled awake
        (pose(eyes="half"), 200), (pose(), 500),
    ],
}


def self_test():
    for name, steps in [("rise", RISE), ("sink", SINK)] + list(GESTURES.items()):
        for kw, ms in steps:
            rows = draw(**kw)
            assert len(rows) == H and all(len(r) == W for r in rows), name
            assert set("".join(rows)) <= set(PALETTE) | {"."}, (name, set("".join(rows)))
            assert ms > 0
    assert draw()[15][12] == "p", "nose"
    assert set(draw(dy=20)) == {"." * W}, "fully sunk pose is empty"
    assert draw(eyes="closed") != draw(), "eye states differ"
