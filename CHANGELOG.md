# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- `install.sh` takes verbs (`install`, `uninstall`, `status`; `--uninstall` still works), backs up
  every file it replaces or removes under `/var/backups/better-touchbar/`, and verifies the service.
- Development scripts merged into `scripts/dev.sh` (`check`, `deploy`, `status`, `shot`,
  `screenshots`, `icons`); `scripts/check.sh` stays the gate.

## [0.1.0] - 2026-09-29

First public release.

### Added
- Touch Bar daemon that takes over from tiny-dfr: control strip, Fn layer, uinput keyboard,
  drawing straight into the appletbdrm scanout buffer.
- Sliders for screen brightness, keyboard backlight and volume (tap, or touch and slide).
- Media controls for the focused MPRIS player: transport, title/artist, seekable timeline.
- Per-app buttons for VS Code, Google Chrome and GNOME Terminal, driven by a GNOME Shell
  extension that reports the focused app.
- Quick settings: Wi-Fi, Bluetooth, Do Not Disturb, Night Light, microphone (red while live).
- Turkish letters through the Turkish (Alt-Q) layout.
- Idle cat with six gestures.
- `install.sh` (install, update, uninstall), tiny-dfr fallback after repeated failures,
  boot/resume recovery (`t2-touchbar-fix`), `tools/fbshot.py` and `tools/touch_sim.py`.

[Unreleased]: https://github.com/KaanErgun/better-touchbar/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KaanErgun/better-touchbar/releases/tag/v0.1.0
