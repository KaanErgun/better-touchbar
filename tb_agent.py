#!/usr/bin/env python3
"""Session-side helper for touchbar.py: media players, volume, focus and quick settings.

These live on the logged-in user's session (D-Bus session bus, PipeWire, GSettings), which
the root daemon cannot reach, so the daemon starts this as that user (runuser, K-003) and talks
JSON lines with it: commands on stdin, state on stdout.

  -> {"c": "media", "action": "PlayPause" | "Next" | "Previous"}
  -> {"c": "seek", "position": seconds}
  -> {"c": "volume", "value": 0.0-1.0}      -> {"c": "get_volume"}
  -> {"c": "toggle", "what": "dnd" | "night_light" | "mic"}
  <- {"t": "media", "name": bus name or null, "status", "title", "artist", "length",
      "position", "can_seek", "app"}
  <- {"t": "volume", "value": 0.0-1.0, "muted": bool}
  <- {"t": "focus", "app": desktop app id or "", "wm_class": str}  (needs the Shell extension)
  <- {"t": "settings", "dnd": bool, "night_light": bool, "mic_muted": bool}
"""
import json
import re
import subprocess
import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

MPRIS = "org.mpris.MediaPlayer2."
OBJ = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
ROOT = "org.mpris.MediaPlayer2"
PROPS = "org.freedesktop.DBus.Properties"
DBUS = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")
# Exported by our GNOME Shell extension (gnome-extension/, K-004): GNOME on Wayland has no other
# way to ask which window has focus.
FOCUS = ("org.gnome.Shell", "/org/gnome/Shell/Extensions/TouchBar", "org.gnome.Shell.Extensions.TouchBar")
NOTIFICATIONS = ("org.gnome.desktop.notifications", "show-banners")
NIGHT_LIGHT = ("org.gnome.settings-daemon.plugins.color", "night-light-enabled")


def send(**msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def parse_volume(text):
    """`wpctl get-volume` output, e.g. 'Volume: 0.40 [MUTED]' -> (0.40, True)."""
    m = re.search(r"Volume:\s*([0-9.]+)", text)
    return (float(m.group(1)) if m else None), "[MUTED]" in text


def wpctl(*args):
    return subprocess.run(["wpctl", *args], capture_output=True, text=True, timeout=2).stdout


class Agent:
    def __init__(self, loop):
        self.loop = loop
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.players = {}   # well-known name -> state dict
        self.owners = {}    # unique name -> well-known name
        self.active = None
        self.bus.signal_subscribe(DBUS[0], DBUS[2], "NameOwnerChanged", DBUS[1], None,
                                  Gio.DBusSignalFlags.NONE, self.on_owner)
        self.bus.signal_subscribe(None, PROPS, "PropertiesChanged", OBJ, PLAYER,
                                  Gio.DBusSignalFlags.NONE, self.on_props)
        self.bus.signal_subscribe(FOCUS[0], FOCUS[2], "FocusChanged", FOCUS[1], None,
                                  Gio.DBusSignalFlags.NONE, self.on_focus)
        for name in self.call(*DBUS, "ListNames")[0]:
            if name.startswith(MPRIS):
                self.add(name)
        self.settings = {}
        for schema, key in (NOTIFICATIONS, NIGHT_LIGHT):
            s = Gio.Settings.new(schema)
            s.connect(f"changed::{key}", lambda *_: self.publish_settings())
            self.settings[schema] = s
        self.mic_muted, self.volume = None, None
        GLib.timeout_add(1000, self.tick)
        GLib.timeout_add(2000, self.poll_audio)
        channel = GLib.IOChannel.unix_new(sys.stdin.fileno())
        GLib.io_add_watch(channel, GLib.PRIORITY_DEFAULT,
                          GLib.IOCondition.IN | GLib.IOCondition.HUP, self.on_stdin)
        self.publish()
        self.poll_audio()
        self.publish_focus()

    def call(self, dest, path, iface, method, params=None, timeout=1000):
        return self.bus.call_sync(dest, path, iface, method, params, None,
                                  Gio.DBusCallFlags.NONE, timeout, None).unpack()

    def prop(self, dest, iface, name, timeout=1000):
        return self.call(dest, OBJ, PROPS, "Get", GLib.Variant("(ss)", (iface, name)), timeout)[0]

    # --- media players -----------------------------------------------------------------
    def add(self, name):
        try:
            owner = self.call(*DBUS, "GetNameOwner", GLib.Variant("(s)", (name,)))[0]
            props = self.call(name, OBJ, PROPS, "GetAll", GLib.Variant("(s)", (PLAYER,)))[0]
        except GLib.Error:
            return
        try:
            app = self.prop(name, ROOT, "DesktopEntry")
        except GLib.Error:
            app = ""
        self.owners[owner] = name
        self.players[name] = {"status": "Stopped", "app": app, "since": time.monotonic()}
        self.update(name, props)

    def update(self, name, changed):
        p = self.players[name]
        if "PlaybackStatus" in changed and changed["PlaybackStatus"] != p["status"]:
            p["status"], p["since"] = changed["PlaybackStatus"], time.monotonic()
        if "CanSeek" in changed:
            p["can_seek"] = bool(changed["CanSeek"])
        if "Metadata" in changed:
            md = changed["Metadata"]
            artist = md.get("xesam:artist") or []
            p.update(title=md.get("xesam:title", ""),
                     artist=", ".join(artist) if isinstance(artist, list) else str(artist),
                     length=md.get("mpris:length", 0) / 1e6,
                     trackid=md.get("mpris:trackid", "/org/mpris/MediaPlayer2/TrackList/NoTrack"))

    def on_owner(self, _conn, _sender, _path, _iface, _signal, params):
        name, old, new = params.unpack()
        if name == FOCUS[0] and new:  # Shell (re)started: ask the extension again
            GLib.timeout_add(2000, lambda: self.publish_focus() and False)
        if not name.startswith(MPRIS):
            return
        if old:
            self.owners.pop(old, None)
            self.players.pop(name, None)
        if new:
            self.add(name)
        self.publish()

    def on_props(self, _conn, sender, _path, _iface, _signal, params):
        _, changed, _ = params.unpack()
        name = self.owners.get(sender)
        if name in self.players:
            self.update(name, changed)
            self.publish()

    def choose(self):
        playing = [n for n, p in self.players.items() if p["status"] == "Playing"]
        if playing:  # the one that started playing most recently
            return max(playing, key=lambda n: self.players[n]["since"])
        return self.active if self.active in self.players else None

    def position(self, name):
        try:
            return self.prop(name, PLAYER, "Position", timeout=300) / 1e6
        except GLib.Error:
            return None

    def publish(self):
        self.active = self.choose()
        if not self.active:
            return send(t="media", name=None)
        p = self.players[self.active]
        send(t="media", name=self.active, status=p["status"], title=p.get("title", ""),
             artist=p.get("artist", ""), length=p.get("length", 0),
             position=self.position(self.active), can_seek=p.get("can_seek", False),
             app=p.get("app", ""))

    def tick(self):
        if self.active and self.players.get(self.active, {}).get("status") == "Playing":
            self.publish()  # position moves; MPRIS does not signal it
        return True

    # --- focus + settings --------------------------------------------------------------
    def publish_focus(self):
        try:
            app, wm_class = self.call(*FOCUS, "GetFocus")
        except GLib.Error:
            app, wm_class = None, None  # extension not loaded (yet)
        send(t="focus", app=app, wm_class=wm_class)
        return False

    def on_focus(self, _conn, _sender, _path, _iface, _signal, params):
        app, wm_class = params.unpack()
        send(t="focus", app=app, wm_class=wm_class)

    def poll_audio(self):
        """PipeWire has no cheap change signal without extra tools; poll every 2 s."""
        volume = parse_volume(wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"))
        if volume != self.volume:
            self.volume = volume
            send(t="volume", value=volume[0], muted=volume[1])
        _, muted = parse_volume(wpctl("get-volume", "@DEFAULT_AUDIO_SOURCE@"))
        if muted != self.mic_muted:
            self.mic_muted = muted
            self.publish_settings()
        return True

    def publish_settings(self):
        send(t="settings",
             dnd=not self.settings[NOTIFICATIONS[0]].get_boolean(NOTIFICATIONS[1]),
             night_light=self.settings[NIGHT_LIGHT[0]].get_boolean(NIGHT_LIGHT[1]),
             mic_muted=bool(self.mic_muted))

    # --- commands ----------------------------------------------------------------------
    def on_stdin(self, _channel, _condition):
        line = sys.stdin.readline()
        if not line:  # daemon went away
            self.loop.quit()
            return False
        try:
            self.command(json.loads(line))
        except (ValueError, KeyError, GLib.Error, subprocess.SubprocessError) as e:
            send(t="error", error=str(e))
        return True

    def command(self, cmd):
        c = cmd["c"]
        if c == "media" and self.active:
            self.call(self.active, OBJ, PLAYER, cmd["action"])
        elif c == "seek" and self.active:
            p = self.players[self.active]
            self.call(self.active, OBJ, PLAYER, "SetPosition",
                      GLib.Variant("(ox)", (p["trackid"], int(cmd["position"] * 1e6))))
            self.publish()
        elif c == "volume":
            v = min(max(float(cmd["value"]), 0.0), 1.0)
            wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", f"{v:.3f}")
            self.volume = (round(v, 2), self.volume[1] if self.volume else False)
        elif c == "get_volume":
            value, muted = parse_volume(wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"))
            send(t="volume", value=value, muted=muted)
        elif c == "toggle":
            what = cmd["what"]
            if what == "mic":
                wpctl("set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle")
                self.poll_audio()
            else:
                schema, key = NOTIFICATIONS if what == "dnd" else NIGHT_LIGHT
                s = self.settings[schema]
                s.set_boolean(key, not s.get_boolean(key))


def main():
    if sys.argv[1:] == ["--self-test"]:
        assert parse_volume("Volume: 0.40 [MUTED]\n") == (0.40, True)
        assert parse_volume("Volume: 1.00\n") == (1.0, False)
        assert parse_volume("") == (None, False)
        return print("agent self-test OK")
    loop = GLib.MainLoop()
    Agent(loop)
    loop.run()


if __name__ == "__main__":
    main()
