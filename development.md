# better-touchbar — development.md

**Bu dosyanın rolü: *Ne*.** Kapsam, ortam, mimari ve kalıcı kararlar burada. Kurallar ve pahalıya
öğrenilmiş tuzaklar `CLAUDE.md`'de, kronoloji `dev-log.md`'de, durum `docs/PROGRESS.md`'de; bitmiş
faz planları `docs/arsiv/` altında. Kullanıcıya dönük tanıtım `README.md` (İngilizce).

---

## §0 Ortam (keşifle doğrulandı, 2026-09-29)

**Hedef makine**

| Ne | Değer |
|---|---|
| Donanım | MacBookPro16,2 (13", 2020, i5-1038NG7, 16 GB), T2 çipi, Touch Bar |
| İşletim sistemi | Ubuntu 24.04.5 LTS, GNOME Shell 46.0, Wayland |
| Çekirdek | t2linux `7.1.8-1-t2-noble` (açılışta sabit; `7.2.8-1-t2-noble` da kurulu, ses sürücüsü hatası yüzünden kullanılmıyor — proje dışı, `macmini-server` `hosts/mbp-ubuntu`) |
| Touch Bar sürücüleri | `appletbdrm` (drivers/gpu/drm/tiny), `hid_appletb_kbd`, `hid_appletb_bl`, `t2bce_core/vhci/audio` (staging, t2bce 0.06) |
| Touch Bar paneli | DRM kartı `appletbdrm`, bağlayıcı `USB-1`, mod 60×2008 (dikey), XRGB8888 dumb buffer |
| Touch Bar dokunmatiği | `Apple Inc. Touch Bar Display Touchpad`, ABS_X 0–32767 (bar boyunca, soldan sağa), ABS_Y 0–127, 11 slot, `INPUT_PROP_DIRECT` |
| Arka ışık | `appletb_backlight` 0–2; ekran `intel_backlight` 0–17777; klavye `:white:kbd_backlight` 0–14660 |
| Python yığını | Python 3.12.3, python3-gi 3.48.2, python3-cairo 1.25.1, python3-gi-cairo 3.48.2, librsvg2 2.58.0, Pango 1.52.1 (hepsi Ubuntu masaüstünde hazır) |
| Ses / oturum | PipeWire 1.0.5, WirePlumber 0.4.17, logind `seat0` |
| Yedek daemon | tiny-dfr 0.3.7-4-noble (t2linux apt deposu) |

**Geliştirme makinesi**: macOS 27, Python 3.14.7 — `gi`/`cairo` **yok**; bu yüzden gate yalnız
çizimden bağımsız mantığı test eder, çizim testi hedefte koşar.

**Kurulu olmayanlar (bilerek, ihtiyaç yok)**: numpy, python-evdev, evtest, libinput araçları,
xkbcli, flatpak. DRM, evdev ve uinput ham ioctl ile konuşulur (K-006).

---

## 1. Kapsam

T2'li Intel MacBook'larda Ubuntu için Touch Bar daemon'u, tiny-dfr'in yerine:

1. Kontrol şeridi (varsayılan) ve Fn basılıyken F1–F12.
2. Ekran parlaklığı, klavye ışığı ve ses için slider (dokun-aç veya dokun-kaydır).
3. Odaktaki uygulama medya oynatırken medya katmanı (MPRIS): önceki/oynat/sonraki, başlık, sürüklenebilir zaman çubuğu, ses.
4. Odaktaki uygulamaya özel tuşlar (VS Code, Chrome, GNOME Terminal; `touchbar.toml`'da genişletilebilir).
5. Hızlı ayarlar: Wi-Fi, Bluetooth, Rahatsız Etme, Gece Işığı, mikrofon (canlıyken kırmızı).
6. Türkçe harfler ş ğ ü ö ç ı İ.
7. Pil ve saat.
8. Boşta kedi: 60 sn girdi yoksa chibi kedi rastgele yerlerde altı hareketten birini yapar.
9. Sağlamlık: uyanış, açılıştaki yoklama hatası, tekrarlanan çökmede tiny-dfr'e devir.

## 2. Mimari

```
 touchbar.py (root, touchbar.service) ── cairo ──▶ appletbdrm dumb buffer (60×2008, matris 90° döndürür)
   │  ◀── evdev: Touch Bar touchpad (EVIOCGRAB), dahili klavye/trackpad (Fn, Shift, aktivite)
   │  ──▶ uinput: "Touch Bar Virtual Keyboard" (tuşlar, kombinasyonlar)
   │  ──▶ sysfs: ekran/klavye ışığı, rfkill (Wi-Fi, Bluetooth), appletb_backlight
   │ JSON satırları (stdin/stdout)
 tb_agent.py (runuser ile oturum sahibi) ── MPRIS, wpctl, GSettings, odak ◀── GNOME Shell eklentisi (D-Bus)
```

Katman önceliği (ilk eşleşen kazanır): **Fn** → **overlay** (slider / hızlı ayarlar / Türkçe) →
**media** → **app** (`[apps]` + `compact`) → **control**. Boşta ve medya çalmıyorken **kedi**.

| Dosya | Sorumluluk |
|---|---|
| `touchbar.py` | Ana döngü, katmanlar, geometri, dokunma, agent bağlantısı, kedi, testler |
| `tb_hw.py` | DRM, evdev/uinput sabitleri, tuş tablosu, sysfs düğmeleri (saf stdlib) |
| `tb_ui.py` | Yalnız boyama (cairo, Pango, librsvg) |
| `tb_agent.py` | Oturum tarafı: medya, ses, odak, ayarlar |
| `cat_art.py` | Kedi çizimi (şekillerden) ve jestler |
| `gnome-extension/` | Odaktaki uygulamayı D-Bus'a veren Shell eklentisi |
| `system/` | systemd birimleri, tiny-dfr drop-in, `t2-touchbar-fix` |
| `install.sh` | Hedef makinede `install` / `uninstall` / `status`; değiştirdiğini `/var/backups/better-touchbar/<zaman>/`'a yedekler |
| `scripts/dev.sh` | Geliştirme Mac'inde `check` / `deploy` / `status` / `shot` / `screenshots` / `icons` (bash 3.2); `scripts/check.sh` kapıya sarmalayıcı |
| `tools/` | `fbshot.py` (ekran → PNG), `touch_sim.py` (sanal dokunma) |

---

## 3. Karar Kayıtları

| ID | Tarih | Karar | Gerekçe | Uygulandığı yer |
|---|---|---|---|---|
| K-001 | 2026-09-28 | tiny-dfr'a yama değil, bağımsız program; tiny-dfr kaynağı okunmaz, analiz edilmez, kopyalanmaz | Upstream deponun `CLAUDE.md`'si yapay zekâ katkısını/analizini istemiyor; Kaan bağımsız yolu seçti | `touchbar.py` başlığı, README Credits |
| K-002 | 2026-09-29 | tiny-dfr yalnız yedek: drop-in `ConditionPathExists=/run/touchbar-fallback`; dakikada 5 çöküşte `touchbar-fallback.service` bayrağı koyar | tiny-dfr birimi `/etc`'de (mask edilemez), udev başlatır (disable etmez); bar hiç ölü kalmamalı | `system/tiny-dfr-50-touchbar.conf`, `system/touchbar.service` |
| K-003 | 2026-09-29 | Oturum tarafı ayrı süreç (`tb_agent.py`), daemon onu `runuser` ile oturum sahibi olarak başlatır; JSON satırları | root, kullanıcının oturum bus'ına ve PipeWire soketine bağlanamaz; kişisel ad koda gömülmez | `touchbar.py` `AgentLink`, `session_user()` |
| K-004 | 2026-09-29 | Odak bilgisi kendi GNOME Shell eklentimizden (D-Bus) | Wayland'da `org.gnome.Shell.Eval` kapalı, başka yol yok | `gnome-extension/`, `tb_agent.py` `FOCUS` |
| K-005 | 2026-09-29 | Türkçe harfler hazır `tr+alt` (Turkish Alt-Q) düzeni + AltGr; özel XKB düzeni yok | Tüm uygulamalarda keysym düzeyinde çalışır; `inet(evdev)` F13–F24'ü ezdiği için F-tuşlu özel düzen işlemez | `touchbar.py` `TURKISH`, `install.sh --turkish` |
| K-006 | 2026-09-29 | Yeni bağımlılık yok: stdlib + Ubuntu'da hazır gi/cairo/librsvg/Pango; DRM/evdev/uinput ham ioctl | pip/venv'siz kurulum, public kullanıcı için tek komut | `tb_hw.py`, `install.sh` 1. adım |
| K-007 | 2026-09-29 | Public, MIT; ikonlar Material Symbols (Apache-2.0) repoda, `dev.sh icons` üretir | Kendi kendine yeten repo, tiny-dfr paketine bağımlılık yok | `LICENSE`, `icons/LICENSE`, `scripts/dev.sh` |
| K-008 | 2026-09-29 | `install.sh` düzenlenmiş `touchbar.toml`'u ezmez; `--update-config` tarihli kopya bırakıp yazar | Kullanıcı ayarı güncellemede kaybolmamalı | `install.sh` 2. adım |
| K-009 | 2026-09-29 | Kedi medya çalarken çıkmaz; kediyi kapatan ilk dokunuş hiçbir tuşa basmaz | Video izlerken kontroller gizlenmesin; uyandırma dokunuşu kazara eylem yapmasın | `touchbar.py` `run()`, `wake()` |
| K-010 | 2026-09-29 | Medya katmanı eklenti varsa yalnız oynatıcının penceresi odaktayken, yoksa "bir şey çalıyorsa" | Kaan'ın tarifi: "odak videodaysa video kontrolleri"; eklentisiz kurulumda da işe yarasın | `touchbar.py` `media_mode()` |

---

## 4. Kapsam dışı (bilerek)

Yeniden açmak yeni bir karar ister.

- **tiny-dfr kodunu değiştirmek veya okumak** — K-001.
- **Touch ID ve haptik geri bildirim** — Linux'ta T2 Secure Enclave desteği yok; Touch Bar'da haptik donanım yok.
- **GNOME dışı masaüstleri** (KDE, Sway…) — odak eklentisi GNOME'a özel; eklentisiz çalışır ama test edilmedi.
- **MacBookPro16,2 dışındaki modeller** — donanım yok; yön farkı için `--flip-along`/`--touch-flip` bayrakları var.
- **Kendi XKB düzeni** — K-005.
- **Odak değişiminde kediyi kapatmak** — odak değişimi girdi sayılmaz; gerçek kullanımda odak zaten tıklama/tuşla değişir.
- **Ses çatlaması** — makineye özgü çekirdek sürücü sorunu; `macmini-server` reposunda çözüldü.

## 5. Fazlar

| Faz | Konu | Durum |
|---|---|---|
| 0 | Boşta kedi prototipi (`touchbar-cat`, tiny-dfr'i durdurup başlatarak) | ✅ 2026-09-27 |
| 1 | tiny-dfr eşdeğerliği: kendi daemon'umuz | ✅ 2026-09-29 |
| 2 | Slider'lar | ✅ 2026-09-29 |
| 3 | Medya katmanı (MPRIS) | ✅ 2026-09-29 |
| 4 | Odak + uygulama tuşları, hızlı ayarlar, Türkçe harfler | ✅ 2026-09-29 |
| 5 | Public yayın | ✅ 2026-09-29, v0.1.0 |

Faz planları ve kabul kriterleri: `docs/arsiv/2026-09-fazlar-0-5.md`.
