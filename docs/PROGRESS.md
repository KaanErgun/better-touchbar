# PROGRESS — better-touchbar

Tek yaşayan durum çizelgesi. Ölçüm: 2026-09-29 (v0.1.0 + belge seti + betik iskeleti).
Kapsam ve kararlar `development.md`'de; kanıtlar `dev-log.md`'de.

## Yayın

- [x] v0.1.0 public — github.com/KaanErgun/better-touchbar (2026-09-29)
- [x] `projects/active/`'e taşındı, belge seti (2026-09-29)

## Donanımda doğrulandı (MacBookPro16,2, Ubuntu 24.04, t2 7.1.8)

- [x] Kontrol şeridi, Fn katmanı çizimi, 15 tuşun kodları (Kaan'ın dokunuşları)
- [x] Parlaklık slider'ı dokun-kaydır (sysfs değeri değişti)
- [x] Ses slider'ı açılıyor, değer `wpctl` ile aynı
- [x] Medya katmanı: otomatik geliş, ⏯, zaman çubuğunda atlama, ✕
- [x] Odak eklentisi ACTIVE, Terminal uygulama tuşları, geri dönüş
- [x] Hızlı ayarlar ve TR katmanı çizimi
- [x] Uyanış (iki `rtcwake` senaryosu) ve reboot (38 sn, 0 failed)
- [x] tiny-dfr yedeği devrede değil (`/run/touchbar-fallback` yok), drop-in çalışıyor

## Açık

- [ ] Kaan testi: TR harfleri gerçek bir metin alanında (ş, Shift+ş, ı, İ)
- [ ] Kaan testi: fiziksel Fn basılıyken F-tuşuna dokunma
- [ ] Kaan testi: Chrome'da YouTube — pencere odaktayken medya katmanı, başka pencerede yok
- [ ] Kaan testi: ses slider'ını parmakla sürükleme
- [ ] Pilde gerçek kullanımda uzun uyku/uyanma (rtcwake testleri geçti)
- [x] Betikler `~/Developments` §7 iskeletinde: `scripts/dev.sh` fiil dağıtıcı, `install.sh` fiiller + yedek + idempotent (2026-09-29)
- [ ] Başka T2 modeli (16,1 / 15,x) — donanım yok; `--flip-along` / `--touch-flip` bayrakları hazır
