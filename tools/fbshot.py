#!/usr/bin/env python3
"""Save what the Touch Bar shows right now as a PNG (run as root on the Mac).

Reads the framebuffer currently on the appletbdrm CRTC and turns the portrait panel back into
the landscape bar you see. Usage: sudo tools/fbshot.py out.png [--scale 2]
"""
import argparse
import ctypes
import mmap
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, "/usr/local/lib/touchbar")
import tb_hw as hw  # noqa: E402

GETCRTC = hw._iowr(0xA1, struct.calcsize(hw.CRTC))
GETFB = hw._iowr(0xAD, struct.calcsize(hw.FB_CMD))


def grab():
    fd = os.open(hw.find_card(), os.O_RDWR)
    n = hw._ioctl(fd, hw.GETRESOURCES, hw.CARD_RES, *([0] * 12))[5]
    crtcs = (ctypes.c_uint32 * n)()
    hw._ioctl(fd, hw.GETRESOURCES, hw.CARD_RES, 0, ctypes.addressof(crtcs), 0, 0, 0, n, 0, 0, 0, 0, 0, 0)
    fb_id = hw._ioctl(fd, GETCRTC, hw.CRTC, 0, 0, crtcs[0], 0, 0, 0, 0, 0, *([0] * 14), b"")[3]
    _, across, length, pitch, _, _, handle = hw._ioctl(fd, GETFB, hw.FB_CMD, fb_id, 0, 0, 0, 0, 0, 0)
    offset = hw._ioctl(fd, hw.MAP_DUMB_IOC, hw.MAP_DUMB, handle, 0, 0)[2]
    with mmap.mmap(fd, pitch * length, mmap.MAP_SHARED, mmap.PROT_READ, offset=offset) as m:
        data = bytes(m)
    os.close(fd)
    return data, across, length, pitch


def to_png(path, data, across, length, pitch, scale=1):
    rows = []
    for y in range(across):             # bar row y (top edge first) = buffer column across-1-y
        col = across - 1 - y
        line = bytearray()
        for x in range(length):         # bar column x = buffer row x
            b, g, r = data[x * pitch + col * 4: x * pitch + col * 4 + 3]
            line += bytes((r, g, b)) * scale
        rows.extend([bytes(line)] * scale)
    raw = b"".join(b"\0" + row for row in rows)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", length * scale, across * scale, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out")
    p.add_argument("--scale", type=int, default=1)
    args = p.parse_args()
    to_png(args.out, *grab(), scale=args.scale)
    print(args.out)


if __name__ == "__main__":
    main()
