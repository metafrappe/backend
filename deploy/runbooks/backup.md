# Yedekleme runbook'u

Bu belge bir ortamın yedeğini almayı ve yedeği denetlemeyi anlatır. Gereksinim G-114'tür.

## Amaç

Yedek, veriyi kayıptan korur. Yedekte üç parça vardır:

- her kiracı sitesinin veritabanı ve dosyaları,
- Keycloak veritabanı,
- eşitleme servisinin veritabanı.

Yedeği `deploy/remote/backup` betiği alır. Betik her yedeğe bir `SHA256SUMS` dosyası yazar. Bu dosya dosyaların özetini tutar.

## Hedefler

Hedefler G-114 gereksinimindendir. Bu hedefler henüz ölçülmedi.

- Kiracı verisi için RPO en çok 24 saattir. RPO, kaybedilebilecek en uzun veri süresidir.
- Press ve Keycloak için RPO en çok 1 saattir. Bu hedef binlog ve WAL kopyası ister. Depoda bu kopya henüz yoktur.
- RTO en çok 8 saattir. RTO, hizmetin geri gelmesi için geçen en uzun süredir.

## Görev sahibi

Hüseyin Cengiz bu runbook'un sahibidir. Hüseyin Cengiz kıdemli DevOps mühendisidir. Sunucudaki her adımı o yapar.

## Ön koşullar

1. Hüseyin Cengiz sunucuya `deploy` kullanıcısıyla bağlanabilir.
2. Ortamın `tenant-web` ve `keycloak-db` container'ları çalışır.
3. rc ve prod için `/etc/atonota/<ortam>/offsite.env` dosyası vardır. Dosyanın anahtarları `deploy/settings/offsite.production.env.example` dosyasındadır.
4. Diskte yedek için yer vardır. `DiskSpaceLow` uyarısı açıksa önce yer açın.

## Adımlar

1. Sunucuda ortamın şu anki sürüm klasörünü bulun. Klasör `/srv/atonota/<ortam>/backend-current` bağıdır.
2. Yedeği başlatın. Örnek komut prod içindir:

   ```sh
   /srv/atonota/prod/bin/backup prod /srv/atonota/prod/backend-current
   ```

3. Betik son satırda yedek klasörünü yazar. Bu yolu not edin.
4. Betik hata verirse çıktıyı okuyun. Sorunu giderip komutu yeniden çalıştırın.

Düzenli yedek sunucuda açıktır. Proje sahibi bunu 26 Kasım 2026 Perşembe günü onayladı (D-16). Düzenli yedeği Hüseyin Cengiz sunucuda kurar. Depoda düzenli yedek kurulumu yoktur.

## Doğrulama

1. Yedek klasörüne girin. Şu komutu çalıştırın: `sha256sum --quiet --check SHA256SUMS`. Komut hiçbir şey yazmamalıdır.
2. Klasörde `keycloak.dump`, `identity-sync.sqlite3` ve `release-id` dosyaları olmalıdır.
3. Her kiracı sitesi için `tenant/<site>` klasörü olmalıdır.
4. rc ve prod için sunucu dışı kopyayı denetleyin. Betik bunu `rclone check` ile kendisi yapar. Çıktıda hata olmamalıdır.
5. İzleme sistemi `BackupMissing` ve `OffsiteBackupMissing` uyarılarını kapalı göstermelidir.

## Depoda olmayan parçalar

Şu parçalar G-114'te geçer ama depoda henüz yoktur:

- Press veritabanının yedeği,
- Press agent veritabanının yedeği,
- imaj deposunun (Registry) yedeği,
- yedeğin şifrelenmesi,
- izleme sistemine son başarılı yedek zamanını yazan ölçüm.

Bu parçalar devir notundadır: `docs/handoff/g113-g114-monitoring-backup.md`.
