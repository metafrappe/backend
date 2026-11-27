# Felaket kurtarma runbook'u

Bu belge bir sunucu tümüyle kaybolunca ne yapılacağını anlatır. Felaket kurtarmanın kısa adı DR'dir. Gereksinim G-114'tür.

## Amaç

Sunucu, disk ya da veri merkezi kaybolabilir. Bu durumda ortam yeni bir sunucuda kurulur. Veri, sunucu dışı yedekten geri gelir.

Hedef RTO en çok 8 saattir. RTO, hizmetin geri gelmesi için geçen en uzun süredir. Bu hedef henüz bir tatbikatla ölçülmedi.

## Görev sahibi

Hüseyin Cengiz bu runbook'un sahibidir. Sunucu, ağ ve geri yükleme adımlarını Hüseyin Cengiz yapar.

Adres değişirse DNS kaydını Asistan Hüseyin günceller. Önce Hüseyin Cengiz kaydın türünü, adını ve değerini yazar. Sonra Asistan Hüseyin kaydı GoDaddy'de girer.

## Ön koşullar

1. Sunucu dışında bir yedek vardır. Bu yedek rc ve prod için zorunludur.
2. Hüseyin Cengiz Object Storage kovasını okuyabilir. Erişim bilgisi yalnız sunucudadır.
3. Son sağlam sürüm paketi Jenkins'te ya da sunucu dışında vardır.
4. Sunucunun gizli ayar dosyaları ayrı bir güvenli yerde saklanır. Bu dosyalar Git'e girmez.

## Adımlar

1. Olayı kaydedin. Kaybın başladığı zamanı yazın.
2. Yeni sunucuyu açın. Sunucuyu `docs/dagitim/ortamlar.md` belgesine göre hazırlayın.
3. Gizli ayar dosyalarını `/etc/atonota/<ortam>/` klasörüne geri koyun.
4. Son sağlam sürüm paketini ilk kurulum olarak kurun. İlk kurulum `ATONOTA_FIRST_INSTALL=1` ister.
5. Son sağlam yedeği Object Storage'dan sunucuya indirin. Örnek: `rclone copy offsite:<kova>/<ortam>/<zaman> /srv/atonota/<ortam>/backups/<zaman>`.
6. Yedeği `deploy/remote/restore` betiğiyle geri yükleyin. Betik önce `SHA256SUMS` özetlerini denetler.
7. Adres değiştiyse DNS kaydını güncelleyin. Bu adımı Asistan Hüseyin yapar.
8. Servisleri başlatın. Sonra bakım kipini kapatın.

## Doğrulama

1. Dış sağlık denetimini çalıştırın: `deploy/bin/health <ortam> <sürüm klasörü>`.
2. `deploy/monitoring/uptime-checks.json` dosyasındaki bütün denetimler başarılı olmalıdır.
3. Örnek bir kiracı sitesine girin. Son yedekteki bir kaydı açın.
4. Keycloak ile giriş yapın. Giriş başarılı olmalıdır.
5. Kaybın başladığı zamanla hizmetin döndüğü zamanı yazın. Aradaki süre RTO hedefinden kısa olmalıdır.

## Tatbikat

DR tatbikatı her çeyrekte bir kez yapılır. Bu sıklık G-114'ün ürün kuralıdır.

- Tatbikat yalnız deneme ortamında yapılır. Canlı veriye dokunulmaz.
- Bir tatbikat Press'in kaybını da içerir.
- Hüseyin Cengiz sonucu yazar. Sonuçta ölçülen RTO ve bulunan eksikler olur.
- Tatbikat elle başlar. Depoda zamanlanmış tatbikat kurulmaz.
