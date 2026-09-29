# better-touchbar

A better Touch Bar for Ubuntu on Intel MacBooks with the T2 chip: a macOS-style control strip
with real sliders, media controls that follow the focused app, per-app buttons, quick settings,
Turkish letters, and a chibi cat that shows up when you leave the machine alone.

![Control strip](docs/screenshots/control.png)
![Volume slider](docs/screenshots/slider.png)
![Media controls](docs/screenshots/media.png)
![VS Code buttons](docs/screenshots/app.png)
![Quick settings](docs/screenshots/quick.png)
![Idle cat](docs/screenshots/cat.png)

*All images are rendered by the daemon's own drawing code (`touchbar.py --screenshots`).*

## Features

- **Control strip** by default, **F1–F12** while Fn is held.
- **Sliders** for screen brightness, keyboard backlight and volume. Tap to open one, or touch
  the key and keep sliding, like on macOS.
- **Media controls** appear when the focused app plays something (anything that speaks MPRIS:
  Chrome, Firefox, VLC, Spotify...): previous / play-pause / next, title and artist, a timeline
  you can drag to seek, and volume.
- **Per-app buttons** for the focused app: VS Code, Google Chrome and GNOME Terminal out of the
  box; add your own in `touchbar.toml`.
- **Quick settings**: Wi-Fi, Bluetooth, Do Not Disturb, Night Light and the microphone. The mic
  key turns red while the microphone is live.
- **Turkish letters** ş ğ ü ö ç ı İ (uppercase while Shift is held) through the
  *Turkish (Alt-Q)* layout, which also puts them on AltGr on the physical keyboard.
- **Battery and clock.**
- **Idle cat**: after a minute without input a pixel cat pops up at random spots and licks its
  paw, stares, slow-blinks, yawns, kneads or dozes off. The first touch brings the buttons back
  (and presses nothing). It stays away while media is playing.
- **Robust**: survives suspend/resume and the Touch Bar display's flaky probe at boot, and hands
  the bar to tiny-dfr if it ever keeps crashing.

## Requirements

- An Intel MacBook with the T2 chip and a Touch Bar. Tested on a MacBookPro16,2 (13", 2020).
- Ubuntu 24.04 or later with the [t2linux](https://wiki.t2linux.org) kernel (`appletbdrm`,
  `t2bce`), GNOME on Wayland.
- Python 3.11+, python3-gi, pycairo, librsvg and Pango: all preinstalled on Ubuntu desktop.
- [tiny-dfr](https://github.com/AsahiLinux/tiny-dfr) is optional; if installed, it becomes the
  fallback.

## Install

```sh
git clone https://github.com/KaanErgun/better-touchbar
cd better-touchbar
./install.sh              # or ./install.sh --turkish for the TR letters
```

Log out and back in once so GNOME Shell loads the focus extension. Without it everything works,
except that media controls show up whenever something plays (not only for the focused app) and
there are no per-app buttons.

`./install.sh status` shows what is running; `./install.sh uninstall` removes it and tiny-dfr
takes the bar back. Every file the installer replaces or removes is kept under
`/var/backups/better-touchbar/<timestamp>/`.

## Configure

The layout lives in `/etc/touchbar/touchbar.toml`. Each button shows an `icon` (an SVG from
`icons/`), `text`, `time` or `battery`, and does one of `key` (a Linux key name or a combo),
`slider`, `layer` or `toggle`. `stretch` makes a button wider. Per-app layouts go under
`[apps]`, keyed by the app's desktop id. The shipped file documents every option. After editing:

```sh
sudo systemctl restart touchbar
```

`./install.sh` never overwrites your edited config; `--update-config` replaces it and keeps a
dated copy.

## How it works

```
                 appletbdrm (DRM)                      Touch Bar touchpad (evdev, grabbed)
                        ▲                                          │
      cairo, rotated    │                                          ▼
 ┌──────────────────────┴──────────────────────────────────────────────────┐
 │ touchbar.py (root, systemd)   layers · sliders · idle cat · uinput keys │
 └──────────────────────┬──────────────────────────────────────────────────┘
          JSON lines    │  runs as the logged-in user
 ┌──────────────────────┴──────────────────────┐        ┌──────────────────────────┐
 │ tb_agent.py   MPRIS · PipeWire · GSettings  │◀─D-Bus─│ GNOME Shell extension    │
 └─────────────────────────────────────────────┘        │ (which app has focus)    │
                                                        └──────────────────────────┘
```

- `touchbar.py` draws straight into a dumb buffer on the Touch Bar's DRM card. The panel is a
  portrait 60×2008 display mounted sideways, so the cairo matrix rotates it.
- It reads the touchpad directly and types through its own uinput keyboard. It also sets
  brightness, keyboard light, Wi-Fi and Bluetooth through sysfs.
- Media players, volume, notification settings and focus live in the user's session. The
  daemon runs `tb_agent.py` as that user and talks to it over a pipe.
- `t2-touchbar-fix` runs at boot and after every resume. It re-enumerates the display when its
  probe times out and restarts the daemon once the re-registered devices have settled.

## Troubleshooting

```sh
journalctl -u touchbar -f          # daemon log
sudo tools/fbshot.py bar.png       # save what the Touch Bar shows as a PNG
sudo tools/touch_sim.py tap 173    # fake a tap without a finger (x in bar pixels)
```

On a model whose panel or touch digitizer runs the other way, add `--flip-along` and/or
`--touch-flip` to `ExecStart` in `/etc/systemd/system/touchbar.service`.

## Development

```sh
./scripts/check.sh                         # hardware-free gate: ABI sizes, layouts, logic, docs
scripts/dev.sh deploy <ssh-host> [options] # ship this checkout to a MacBook, install, assert
scripts/dev.sh status <ssh-host>           # what is running there (read-only)
scripts/dev.sh shot <ssh-host> [out.png]   # what its Touch Bar shows right now
scripts/dev.sh screenshots <ssh-host>      # regenerate docs/screenshots with the real drawing code
scripts/dev.sh icons                       # regenerate icons/ from Material Symbols
```

Design notes, decisions and the development log are kept in Turkish: `development.md`,
`CLAUDE.md`, `dev-log.md`, `docs/PROGRESS.md`.

## Credits

- The [t2linux](https://t2linux.org) community, for the kernel, the wiki and the Touch Bar
  display re-enumeration trick.
- [tiny-dfr](https://github.com/AsahiLinux/tiny-dfr) is the Touch Bar daemon this replaces and
  falls back to. better-touchbar is an independent implementation and contains no tiny-dfr code.
- Icons: [Material Symbols](https://fonts.google.com/icons) by Google, Apache License 2.0.

## License

MIT, see [LICENSE](LICENSE). The icons keep their Apache 2.0 license (`icons/LICENSE`).
