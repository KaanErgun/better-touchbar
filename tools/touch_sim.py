#!/usr/bin/env python3
"""Fake Touch Bar touches for testing without a finger (run as root on the Mac).

Creates a uinput device with the real touchpad's name; touchbar.py picks it up (and grabs it)
on its next input rescan, then sees taps and drags exactly like real ones.
Usage: sudo tools/touch_sim.py tap X [X ...] | drag X1 X2 [--steps N] | hold X SECONDS
       sudo tools/touch_sim.py seq "tap X" "drag X1 X2" "sleep S" "shot out.png" ...
X is a position along the bar in pixels (0 = left end, 2008 = right end). `seq` runs several
steps on one fake device (no 6 s rescan wait between them); `shot` saves the bar via fbshot.
"""
import argparse
import fcntl
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, "/usr/local/lib/touchbar")
import tb_hw as hw  # noqa: E402

UI_SET_ABSBIT = 0x40045567  # _IOW('U', 103, int)
ABS_Y = 0x01
LENGTH, TOUCH_MAX_X = 2008, 32767
NAME = "Apple Inc. Touch Bar Display Touchpad"


class FakeTouchpad:
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY)
        for evbit in (hw.EV_KEY, hw.EV_ABS, hw.EV_SYN):
            fcntl.ioctl(self.fd, hw.UI_SET_EVBIT, evbit)
        fcntl.ioctl(self.fd, hw.UI_SET_KEYBIT, hw.BTN_TOUCH)
        for absbit in (hw.ABS_X, ABS_Y):
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, absbit)
        absmax = [0] * 64
        absmax[hw.ABS_X], absmax[ABS_Y] = TOUCH_MAX_X, 127
        os.write(self.fd, struct.pack(hw.UINPUT_USER_DEV, NAME.encode(), hw.BUS_VIRTUAL,
                                      0x05AC, 0x8302, 1, 0, *absmax, *([0] * 192)))
        fcntl.ioctl(self.fd, hw.UI_DEV_CREATE)
        time.sleep(6)  # touchbar.py rescans its inputs every 5 s

    def _emit(self, *events):
        os.write(self.fd, b"".join(hw.EVENT.pack(0, 0, t, c, v) for t, c, v in events)
                 + hw.EVENT.pack(0, 0, hw.EV_SYN, hw.SYN_REPORT, 0))

    def at(self, x, down=True):
        raw = round(max(0, min(LENGTH, x)) / LENGTH * TOUCH_MAX_X)
        self._emit((hw.EV_ABS, hw.ABS_X, raw), (hw.EV_ABS, ABS_Y, 64), (hw.EV_KEY, hw.BTN_TOUCH, int(down)))

    def up(self):
        self._emit((hw.EV_KEY, hw.BTN_TOUCH, 0))

    def close(self):
        fcntl.ioctl(self.fd, hw.UI_DEV_DESTROY)
        os.close(self.fd)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tap").add_argument("x", type=float, nargs="+")
    d = sub.add_parser("drag")
    d.add_argument("x1", type=float)
    d.add_argument("x2", type=float)
    d.add_argument("--steps", type=int, default=20)
    h = sub.add_parser("hold")
    h.add_argument("x", type=float)
    h.add_argument("seconds", type=float)
    sub.add_parser("seq").add_argument("steps", nargs="+")
    args = p.parse_args()
    pad = FakeTouchpad()
    try:
        if args.cmd == "seq":
            for step in args.steps:
                run(pad, *step.split())
        elif args.cmd == "tap":
            for x in args.x:
                run(pad, "tap", x)
        elif args.cmd == "drag":
            run(pad, "drag", args.x1, args.x2, args.steps)
        else:
            run(pad, "hold", args.x, args.seconds)
        time.sleep(0.5)
    finally:
        pad.close()


def run(pad, cmd, *a):
    if cmd == "tap":
        pad.at(float(a[0]))
        time.sleep(0.08)
        pad.up()
        time.sleep(0.4)
    elif cmd == "drag":
        x1, x2, steps = float(a[0]), float(a[1]), int(a[2]) if len(a) > 2 else 20
        for i in range(steps + 1):
            pad.at(x1 + (x2 - x1) * i / steps)
            time.sleep(0.03)
        pad.up()
        time.sleep(0.3)
    elif cmd == "hold":
        pad.at(float(a[0]))
        time.sleep(float(a[1]))
        pad.up()
    elif cmd == "sleep":
        time.sleep(float(a[0]))
    elif cmd == "shot":
        import fbshot
        fbshot.to_png(a[0], *fbshot.grab())
        print(a[0], flush=True)
    else:
        raise SystemExit(f"unknown step: {cmd}")


if __name__ == "__main__":
    main()
