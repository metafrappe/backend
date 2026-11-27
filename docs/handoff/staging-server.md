# Hazırlık sunucusu

## Kapsam ve görev sahibi

Bu not hazırlık sunucusunu ve G-110 gereksinimini kapsar.
Görev sahibi DevOps sorumlusudur.

## Bağımlılıklar

- DevOps sorumlusu Hetzner sunucusuna ve özel ağa erişebilmelidir.
- Hazırlık ortamı yalnız deneme verisiyle çalışır.
- Eski denetim raporu gerçek veriden önce başka bir iş istiyordu. Bu rapor depoda yoktur. Gerçek veri kullanmadan önce bu koşulu proje sahibine sorun.
- Press denemesi bu sunucuyu kullanır. Ayrıntı [Press devir notundadır](press-provisioning.md).

## Adımlar

1. Hetzner'de canlı sunucuyla aynı tipte bir hazırlık sunucusu ayırın.
2. Sunucuya Docker Engine kurun.
3. Her ortam için ayrı Compose projesi tanımlayın. Compose, servisleri birlikte çalıştırır.
4. Ortam ayarlarını Press kayıtlarında ve ortam değişkenlerinde tutun.
5. Yerel servisleri Mac'te Colima ile doğrulayın.
6. Hazırlık ortamında yalnız deneme verisiyle başlayın.
7. Hazırlık ortamına özel ağdan erişimi doğrulayın.
8. Ortam geçişlerinde Jenkins'in onay düğmelerini kullanın.

Yerel kurulum Frappe 16, MariaDB, Redis, Keycloak ve Agent çalıştırır. Press ayrı bir Frappe 16 çalışma grubu kullanır.
Alpha son kodu çalıştırır. Beta ürün ekibinin deneme ortamıdır. Alpha ile beta aynı sunucuyu paylaşır.
RC son kabul ortamıdır. RC ile prod ayrı sunucularda çalışır. Prod, müşterilerin kullandığı canlı ortamdır.
Geçiş sırası alpha, beta, rc ve prod olur.

## İlk kurulum

Bu bölümün görev sahibi DevOps sorumlusudur. Adımlar sunucuda henüz denenmedi.

Bir ortamda ilk kez çalışan sürüm yoktur. Bu durumda `apply` betiği yalnız `ATONOTA_FIRST_INSTALL=1` ile çalışır. Jenkins bu değişkeni sunucuya geçirmez. Bu yüzden DevOps sorumlusu ilk kurulumu sunucuda elle yapar. Betik `deploy/remote/apply` dosyasıdır.

Aşağıdaki örneklerde `<ortam>` ortamın adıdır. Örneğin `alpha` yazın. `<paket>` paketin kimliğidir. Örneğin `backend-1a2b3c4d5e6f-b1` yazın.

1. `/etc/atonota/<ortam>/` altındaki sır dosyalarını açın. Dosya listesi ve anahtarlar [ortamlar belgesinde](../dagitim/ortamlar.md) yazılıdır. Her dosyanın izni `0600` olur. Dosyanın sahibi `deploy-<ortam>` kullanıcısıdır.
2. `/etc/atonota/edge.env` dosyasını da açın.
3. Jenkins'te o ortamın dağıtımını başlatın. Jenkins paketi `/srv/atonota/<ortam>/incoming/<paket>` klasörüne kopyalar. Sonra betik "has no running release" hatasıyla durur. Bu hata ilk kurulumda beklenir.
4. Sunucuya `deploy-<ortam>` kullanıcısıyla girin.
5. Betiği ilk kurulum değişkeniyle çalıştırın: `ATONOTA_FIRST_INSTALL=1 /srv/atonota/<ortam>/incoming/<paket>/apply <ortam> /srv/atonota/<ortam>/incoming/<paket>`.
6. Betik veritabanlarını ve Keycloak'ı başlatır. Kiracı sitesi yoksa betik "does not exist" hatasıyla durur. Bu hata da ilk kurulumda beklenir.
7. Her kiracı sitesini `bench new-site <site adı>` komutuyla açın. Site adları ortam dosyasındaki `ATONOTA_TENANT_SITES` değerindedir. Komutu paketin Compose projesinde, terminalli olarak çalıştırın. Komutun biçimi `deploy/remote/common.sh` dosyasındaki `stack` işlevindedir.
8. `bench new-site` veritabanı kök parolasını sorar. Parolayı soruya yazın. Parolayı komut satırına yazmayın. Parola `tenant-db.env` dosyasındadır.
9. Sitenin `site_config.json` ayarlarını yazın. Ayar listesi `deploy/settings/tenant-site.production.env.example` dosyasındadır.
10. `/srv/atonota/<ortam>/backend-pending` bağlantısını silin.
11. 5. adımdaki komutu yeniden çalıştırın. Betik siteleri taşır ve bütün servisleri başlatır.
12. Betik "is current" yazınca ilk kurulum biter. Sonraki sürümleri Jenkins normal yolla taşır.

Press sitesi ayrı adımlarla açılır. Bu adımlar [Press imajı belgesindedir](../dagitim/press-imaji.md). Press yalnız alpha ve beta'da açılır.

prod ve rc ilk kurulumda da sunucu dışı yedek ister. `offsite.env` dosyası yoksa betik durur.

## Doğrulama

- Hazırlık sunucusunda `docker compose ls` ile proje adlarını karşılaştırın.
- Hazırlık projesinde `docker compose ps` ile servis durumlarını denetleyin.
- Mac'te `colima status -p factory` ile yerel çalışma ortamını kontrol edin.
- Her ortamın ayar ve servis kontrolünü ayrı kayda alın. Canlı ortamın kanıtını yetkili işletim kaydından alın.

## Kabul ölçütü

Hazırlık sunucusu deneme verisiyle çalışır. DevOps sorumlusu servis ve erişim sonuçlarını kaydeder.
G-110, ortam ayrımı ve ayrı çalışma kanıtları tamamlanınca kapanır.

- [Proje kaydı](../../PROJECT-RECORD.md)
- [G-110](https://karacaismail.github.io/frappesetup/gereksinimler/#req-G-110)
