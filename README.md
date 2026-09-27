# touchbar-cat

A chibi cat pops up on the Touch Bar of a T2 MacBook running Linux whenever the machine
has been idle for a while: it rises at a random spot, does something cute, sinks, and shows
up somewhere else a few seconds later. Touch the bar or use the keyboard/trackpad and the
normal `tiny-dfr` buttons come straight back.

Gestures (`cat_art.GESTURES`): `pati_yalama` (paw licking), `dik_dik_bakma` (intense
stare), `yavas_goz_kirpma` (slow blink + heart), `esneme` (yawn), `yogurma` (kneading),
`uyuklama` (dozing off, then startled awake). The head is drawn from shapes in
`cat_art.py`; a gesture is a timed list of poses.

It is an independent daemon (Python standard library only), not a tiny-dfr patch:

1. It watches the internal keyboard, trackpad, Touch Bar touchpad and tiny-dfr's virtual
   input device for activity.
2. After `--idle` seconds of silence it stops `tiny-dfr.service`, becomes DRM master of the
   `appletbdrm` card and plays cat scenes in a dumb buffer.
3. On the first input event it releases the card and starts `tiny-dfr.service` again.
   The unit's `ExecStopPost` restarts tiny-dfr even if the daemon crashes.

Tested on MacBookPro16,2, Ubuntu 24.04, t2 kernel 7.2.8.

## Use

```sh
./scripts/check.sh                      # hardware-free gate
./scripts/deploy.sh user@host           # install + enable the systemd service
sudo python3 /usr/local/lib/touchbar-cat/touchbar_cat.py --demo 30 [--only esneme]   # on the Mac
```

Options (edit `ExecStart` in `touchbar-cat.service`): `--idle SECONDS` (60),
`--brightness 1|2` (1), `--pause-min`/`--pause-max` seconds between scenes (2/6),
`--only GESTURE`, `--flip-across` if the cat shows up upside down on another model.

Uninstall: `sudo systemctl disable --now touchbar-cat && sudo rm -r /usr/local/lib/touchbar-cat /etc/systemd/system/touchbar-cat.service`
