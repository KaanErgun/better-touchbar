# dev-log — better-touchbar

Kronoloji. **En yeni en altta.** Her girişin `Sonuç:` satırı ölçülmüş bir kanıt taşır. Denenip
işe yaramayan yollar `Çıkmaz:` / `Neden:` / `Kural:` ile kaydedilir; `Kural:` satırları
`CLAUDE.md`'ye ya da kapıya taşınır.

---

## 2026-09-27 — Touch Bar düzeni (tiny-dfr config) ve açılıştaki appletbdrm hatası
**Yapıldı:** tiny-dfr için macOS tarzı `config.toml` (kontrol şeridi varsayılan, Fn → F1–F12) ve 3 ikon;
`t2-touchbar-fix` betiği + birimi: appletbdrm bağlanmamışsa 05ac:8302'ye yavaş 0→2 USB yapılandırma reset.
**Sonuç:** ✅ Tuşlar Kaan'ın testinde çalıştı; reboot'ta appletbdrm `minor 2` ile bağlandı, `tiny-dfr` active.
**Çıkmaz:** `modprobe -r appletbdrm && modprobe appletbdrm`.
**Neden:** Sorun sürücü yüklemesi değil, cihaz hazır olmadan yoklama (-110 zaman aşımı).
**Kural:** appletbdrm -110 → yeniden yükleme değil, yavaş bConfigurationValue reset (GOTCHAS 2).

---

## 2026-09-27 — Faz 0: bağımsız kedi daemon'u (touchbar-cat)
**Yapıldı:** `touchbar_cat.py`: 60 sn boşta tiny-dfr'i durdurur, appletbdrm'e ham DRM ioctl ile dumb
buffer açar, kedi çizer; ilk girdide bırakıp tiny-dfr'i başlatır. tiny-dfr kaynağı okunmadı (K-001).
**Sonuç:** ✅ 45 sn demo hatasız; servis 16:31:44'te (60 sn boşta) kediyi açtı, `event8` ile kapandı.
**Çıkmaz:** İlk demo 0 sn'de bitti.
**Neden:** tiny-dfr durunca onun uinput aygıtı kayboluyor; `select` onu okunabilir döndürüyor, ENODEV girdi sayıldı.
**Kural:** Yalnız gerçek olay verisi girdi sayılır (GOTCHAS 7).

---

## 2026-09-27 — Faz 0: chibi kafa ve 6 jest
**Yapıldı:** `cat_art.py`: kafa şekillerden üretilir (elips, üçgen, otomatik dış çizgi), pozlar
parametreli; pati yalama, dik dik bakma, yavaş göz kırpma, esneme, yoğurma, uyuklama. Kedi alttan
yükselir, rastgele yerde jest yapar, batar.
**Sonuç:** ✅ 75 sn demo 88 sn sürdü (son sahne tamamlandı), 10 sahne, 5 farklı jest, appletbdrm hata 0.
**Çıkmaz:** İlk sprite (22×12 hücre, 4 px) kaba; pati beyaz dikdörtgen olarak ağızda diş gibi durdu.
**Neden:** Çözünürlük düşük; pati yüzle aynı renkte kolla birleşince seçilmiyordu.
**Kural:** Küçük ekranda tanınırlık ikonik detaydan gelir (pembe pati yastıkları); önizlemeyi büyütüp bak.

---

## 2026-09-27 — Uyanışta Touch Bar ölüyor
**Yapıldı:** `t2-touchbar-fix` uyku hedeflerine `WantedBy` + `After`; `udevadm settle` sonrası tiny-dfr'i başlatır.
Kedi daemon'u ENODEV'de settle + 2 sn bekleyip devreder.
**Sonuç:** ✅ İki `rtcwake -m no -s 40` + `systemctl suspend` testi: normal şeritte ve kedi açıkken
uyanıştan 2 sn sonra `tiny-dfr` active, `NRestarts=0`.
**Çıkmaz:** —
**Neden:** Uyanışta DRM kartı yeniden kaydediliyor; `BindsTo=` tiny-dfr'i durduruyor, tetikleyici touchpad input'u yeniden eklenmiyor.
**Kural:** GOTCHAS 3. Test için doğrudan `rtcwake -m mem` değil, `rtcwake -m no` + `systemctl suspend` (sleep hedefleri çalışsın).

---

## 2026-09-29 — Faz 1: kendi daemon'umuz (tiny-dfr eşdeğerliği)
**Yapıldı:** `touchbar.py` + `tb_hw.py` + `tb_ui.py`: cairo doğrudan scanout buffer'a (döndürülmüş matris),
uinput klavye, touchpad grab, kedi süreç içinde. tiny-dfr drop-in + `touchbar-fallback.service` (K-002).
**Sonuç:** ✅ Framebuffer okumasında 15 tuş arka planı (13×~103 px + 2×~207 px); Kaan'ın testinde tuş
kaydı 88 olay, parlaklık/ses/klavye ışığı/Mission Control/Launchpad kodları doğru.
**Çıkmaz:** `systemctl mask tiny-dfr`.
**Neden:** Birim dosyası `/etc/systemd/system`'de; mask aynı yola `/dev/null` bağlantısı koyamaz.
**Kural:** GOTCHAS 4 — drop-in koşulu.

---

## 2026-09-29 — Faz 2–4: slider, medya, odak, hızlı ayarlar, Türkçe
**Yapıldı:** `tb_agent.py` (runuser, MPRIS/wpctl/GSettings/odak, K-003), GNOME Shell eklentisi (K-004),
katmanlar, `install.sh`, Material Symbols ikonları, `tools/fbshot.py` + `tools/touch_sim.py`.
**Sonuç:** ✅ Hepsi donanımda, ekran görüntüsüyle: parlaklık dokun-kaydır 5457 → 9184 (beklenen +%21);
ses slider'ı %52 = `wpctl` 0.52; VLC ile medya katmanı kendiliğinden geldi, ⏯ çalıştı, ortaya dokunuş
0:31'e atladı (60 sn dosya); Terminal odaktayken Terminal tuşları (`GetFocus` →
`org.gnome.Terminal.desktop`); reboot 38 sn, 0 failed.
**Çıkmaz:** Sanal touchpad dokunuşları iki kez sessizce kayboldu.
**Neden:** Girdi taraması yalnız ana döngüdeydi (kedi modunda hiç yok) ve normal moddaki `select` 60 sn'ye
kadar bekliyordu.
**Kural:** GOTCHAS 5 — tarama `poll()`'da, `select` ≤5 sn.

---

## 2026-09-29 — Faz 5: public yayın v0.1.0
**Yapıldı:** README (İngilizce, görseller `--screenshots` ile), MIT `LICENSE`, `CHANGELOG.md`, deploy hedefi
argüman, geçmiş taraması, GitHub adı `touchbar-cat` → `better-touchbar`, public, konu etiketleri,
annotated `v0.1.0`.
**Sonuç:** ✅ PUBLIC; uzak `main` = yerel `5d39fba`; anonim sayfa / README / görsel 200 / 200 / 200;
geçmişte gizli bilgi 0, yapay zekâ imzası 0.
**Çıkmaz:** Görünürlük değişiminden hemen sonra `git ls-remote` 403 "repository is disabled".
**Neden:** GitHub'ın görünürlük işlemesi sırasında kısa süreli kilit.
**Kural:** GOTCHAS 14 — 10 sn bekleyip yeniden dene.

---

## 2026-09-29 — projects/active'e taşıma ve belge seti
**Yapıldı:** `~/Developments/experiments/better-touchbar` → `~/Developments/projects/active/better-touchbar`;
`development.md` (§0, K-001…K-010, kapsam dışı), `CLAUDE.md`, `dev-log.md`, `docs/PROGRESS.md`,
`docs/arsiv/2026-09-fazlar-0-5.md`; kodda karar atıfları; kapıya `CLAUDE.md` ≤120 satır denetimi.
Kod davranışı değişmedi.
**Sonuç:** ✅ Kapı exit 0 (self-test, 51 düzen tuşu, 39 ikon, belge denetimi).

---

## 2026-09-29 — Betikler `~/Developments` §7 iskeletine
**Yapıldı:** `scripts/dev.sh` fiil dağıtıcı (`check`, `deploy`, `status`, `shot`, `screenshots`, `icons`; macOS
bash 3.2), `scripts/check.sh` ona sarmalayıcı; `scripts/deploy.sh` ve `scripts/fetch-icons.sh` kaldırıldı.
`install.sh` fiillere geçti (`install`/`uninstall`/`status`, eski `--uninstall` de çalışır): renkli numaralı
adımlar, özet, değiştirilen/silinen her dosyanın `/var/backups/better-touchbar/<zaman>/` yedeği, `put()` ile
idempotent kurulum, sonunda servis doğrulaması. Kapıdaki SVG denetimi XML ayrıştırmadan (defusedxml
bağımlılığı eklemeden, K-006) yapılıyor.
**Sonuç:** ✅ `/bin/bash` 3.2.57 ile: `dev.sh check` exit 0; `deploy` 8/8 adım, 4 dosya değişti + 4 yedek
(`20260929-102717`); ikinci `deploy` **0 dosya değişti**; `status` touchbar active, eklenti ACTIVE, yardımcı 1;
`shot` PNG kontrol şeridini gösterdi.
**Çıkmaz:** `status` yardımcı için "2 process" gösterdi.
**Neden:** `runuser` sarmalayıcısının komut satırında da `tb_agent.py` geçiyor.
**Kural:** Süreç sayarken sarmalayıcıyı dışla (`pgrep -fa … | grep -vc runuser`) — kodda uygulandı.

---

## 2026-09-29 — Sürüm v0.2.0
**Yapıldı:** `CHANGELOG.md` `[Unreleased]` → `[0.2.0] - 2026-09-29` (+ karşılaştırma bağlantıları);
`docs/PROGRESS.md` Yayın maddesi; `chore(release): 0.2.0` commit'i ve annotated `v0.2.0`. Sürüm dizesi
taşıyan manifest yok (`git grep` 0 eşleşme); sürümün tek kaynağı CHANGELOG + etiket. Kod değişikliği
yapılmadı.
**Sonuç:** ✅ Kapı exit 0; uzak `main` = `878cbbc`, `refs/tags/v0.2.0^{}` = `878cbbc`; anonim
`releases/tag/v0.2.0`, `compare/v0.1.0...v0.2.0`, `blob/v0.2.0/CHANGELOG.md` 200 / 200 / 200.
