# CLAUDE.md — better-touchbar

`~/.claude/CLAUDE.md` ve `~/Developments/CLAUDE.md` önce gelir. Bu dosya yalnız bu repoya özgü
kuralları ve pahalıya öğrenilmiş tuzakları tutar; durum cümlesi yazılmaz. Dil: Türkçe; kod,
yorumlar, commit mesajları ve `README.md` İngilizce (public repo).

## Belgeler

| Dosya | Rol |
|---|---|
| `development.md` | **Ne**: kapsam, §0 ortam, mimari, Karar Kayıtları (K-xxx), kapsam dışı |
| `CLAUDE.md` | **Nasıl**: kurallar ve tuzaklar |
| `dev-log.md` | **Kronoloji**, en yeni en altta, `Sonuç:` hep ölçülmüş |
| `docs/PROGRESS.md` | **Durum**: tek yaşayan çizelge |
| `docs/arsiv/` | Kapanmış faz planları |

## Komutlar

```sh
./scripts/check.sh                                       # KAPI (= scripts/dev.sh check)
scripts/dev.sh deploy <host> --update-config --turkish   # hosta YAZAR → her seferinde Kaan'a sor
scripts/dev.sh status|shot|screenshots <host>            # salt-okuma / Touch Bar PNG / README görselleri
scripts/dev.sh icons                                     # icons/ yeniden üret
./install.sh [install] [--turkish] [--update-config] | uninstall | status   # hedef makinede
sudo tools/touch_sim.py seq "tap X" "drag A B" "shot f.png"                  # hedefte, elsiz dokunma
```

Kapı hiçbir hosta dokunmaz ve çizim yapmaz; çizim `install.sh` 3. adımında hedefte test edilir.

## Kurallar

1. tiny-dfr kaynağını okuma, analiz etme, kopyalama (K-001). Yalnız kurulu paketin davranışı,
   config şablonu ve ikonları kullanılabilir.
2. Yeni bağımlılık yok: stdlib + Ubuntu masaüstünde hazır gi/cairo/librsvg/Pango (K-006).
3. Geometri ve durum `touchbar.py`'de; `tb_ui.py` yalnız boyar. Test edilen mantık `gi` import
   etmez — geliştirme Mac'inde `gi` yok, kapı orada koşar.
4. Kişisel ad, host, kullanıcı koda gömülmez: oturum sahibi logind'den (K-003), deploy hedefi argüman.
5. `docs/screenshots/` `dev.sh screenshots`, `icons/` `dev.sh icons` çıktısıdır; elle düzenlenmez.
   Betikler `~/Developments` §7 iskeletinde; `dev.sh` macOS bash 3.2'de koşar (`/bin/bash` ile sına).
6. Donanımda sına: `touch_sim` + `fbshot`. Dokunacağın x'in o katmanda hangi tuşa düştüğünü hesapla
   (sessiz, mikrofon, harfler kullanıcının oturumunu etkiler); değiştirdiğin değeri geri al.
7. Push, etiket, görünürlük dışa dönük: her seferinde Kaan'a sor. Sürüm = CHANGELOG + annotated tag.
8. Bir karar değişirse önce `development.md` Karar Kayıtları, sonra kod; kodda `K-xxx` atfı kalır.

## Bilerek böyle (düzeltme)

- Odak değişimi girdi sayılmaz: kedi açıkken uzaktan açılan pencere kediyi kapatmaz.
- Kediyi kapatan ilk dokunuş hiçbir tuşa basmaz; medya çalarken kedi çıkmaz (K-009).
- Ses ve mikrofon 2 sn'de bir yoklanır (PipeWire'da ek araçsız değişim sinyali yok).
- Yedek tiny-dfr düzeninde slider yok; tiny-dfr'in yapamadığı şey.
- Eklentisiz kurulumda medya katmanı "bir şey çalıyorsa" gelir, uygulama tuşları hiç gelmez (K-010).

## GOTCHAS

1. **Panel dikey 60×2008, 90° dönük.** Buffer x=0 barın ALT kenarı, buffer y=0 SOL ucu. Belirti:
   yön yanlışsa kedi baş aşağı / tuşlar ters. Kanıt: 2026-09-27 kedi testi; 2026-09-29 framebuffer
   okuması (15 arka plan, geniş iki tuş yüksek y'de).
2. **appletbdrm açılışta ara sıra -110 ile bağlanmaz.** `modprobe -r` + yükleme işe yaramaz; 05ac:8302'ye
   yavaş `bConfigurationValue` 0 → (1 sn) → 2 çözer (`t2-touchbar-fix`). Kanıt: 2026-09-27.
3. **Uyanışta t2bce DRM kartını ve girdileri yeniden kaydeder.** Eski fd ENODEV; tiny-dfr `BindsTo=` ile
   durur ve touchpad input'u yeniden eklenmediği için udev onu başlatmaz → bar ölü. Çözüm:
   `t2-touchbar-fix` uyku hedeflerine `WantedBy`+`After`, sahibini yeniden başlatır. Kanıt:
   2026-09-27 17:57/18:03 olayı; iki `rtcwake` senaryosu.
4. **tiny-dfr birimi `/etc/systemd/system`'de**: mask edilemez ("already exists"); udev
   `SYSTEMD_WANTS` ile başlar, disable etmez. Drop-in `ConditionPathExists` (K-002).
5. **Hot-plug girdiler yalnız `poll()` taramasında görülür.** Normal modda `select` ≤5 sn olmalı,
   kedi modunda da taranmalı. Belirti: sanal touchpad dokunuşları sessizce kayboldu. Kanıt: 2026-09-29.
6. **uinput'ta BTN_* bitleri** (0x100–0x15f, 0x2c0+) açılırsa aygıt fare sanılır; yalnız KEY aralıkları.
7. **Touchpad EVIOCGRAB ile alınmazsa** GNOME onu işaretçi aygıtı sayar. tiny-dfr çalışırken touchpad
   onundur; eski kedi daemon'u aktiviteyi tiny-dfr'in uinput'undan okurdu, o aygıt tiny-dfr durunca
   kaybolur — ENODEV'i girdi sayma (ilk demo 0 sn'de bitmişti).
8. **root oturum bus'ına bağlanamaz**: agent `runuser` ile. Giriş ekranı oturumu `Class=greeter` →
   agent başlamaz, medya/odak yok.
9. **GNOME 46 Wayland'da `org.gnome.Shell.Eval` kapalı** (`(false, '')`); yeni kurulan eklenti
   ancak logout/login sonrası yüklenir.
10. **xkb `inet(evdev)` layout'tan sonra gelir** ve F13–F24'ü XF86 tuşlarıyla ezer; özel harf için
    F-tuşlu düzen işlemez (K-005).
11. **Kimlik bilgisi taraması** "passwordless", "getent passwd" gibi kelimelerde yanlış alarm verir;
    eşleşen satırı okuyup karar ver.
12. **`dev.sh deploy/screenshots` `git ls-files` ile paketler**: `git add` edilmemiş yeni dosya hedefe gitmez.
13. **MPRIS konum sinyali yok** → agent saniyede bir sorar. `DesktopEntry` ("google-chrome") ile odak
    app id ("google-chrome.desktop") normalize edilip eşleştirilir.
14. **Görünürlük değişiminden hemen sonra** `git ls-remote` 403 "repository is disabled" dönebilir;
    ~10 sn sonra düzelir. Kanıt: v0.1.0 yayını.
