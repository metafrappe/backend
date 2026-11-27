# G-83 ve G-88 devir notu

Bu not Hüseyin Cengiz'e yöneliktir.
Çalışma dalı `pc/ai-service-setup` olur.
Yerel kurulum canlı kurulum kanıtı değildir.
Bu dal henüz birleştirmeye hazır değildir.
Test kapısı ortak kilidi bekliyor.
G-88 sözleşmesi ve testleri hazırdır. G-88 uygulama kodu henüz yazılmadı.
Önce düşen test koşmadan uygulama koduna geçilmedi.
Güncel kanıt `ai-service-setup-status.md` dosyasındadır.

## Kapsam

G-83 tamamen kapanmadı. Bu dal model geçidinin yerel kurulumunu tanımlar.
Model geçidi, seçilen sağlayıcıya model isteği gönderir.
Ayrı ajan servisi MVP sonrasında kurulacaktır.
Ajan servisinin ayrı PostgreSQL veritabanı ve Redis kuyruğu açık iştir.

G-88 sözleşmesi açık sayfanın bağlamını denetlemeyi gerektirir.
Bağlam, sayfanın kayıt türünü ve seçili kayıtlarını bildiren ipucudur.
Bağlam kullanıcıya ek yetki vermez.
Mevcut akışta her yazma önce öneri açar.
İnsan, önizlemeyi görüp ayrı uçtan onay verir.

Panel, dar ekran ve klavye parçası kapsam dışı: atonota-web.
Arayüz bağlantısı tamamlanmadan G-88 tamamen kapanmaz.

## Yerel kurulum

Tanım `dev/ai-service/compose.yaml` dosyasındadır.
Tanım mevcut kiracı imajını, MariaDB veritabanını ve Redis kuyruğunu kullanır.
İşçi, kuyruktaki işleri işler. Zamanlanmış görev başlatılmaz.
Redis kuyruğu kalıcı birimde saklanır.
Caddy, şifreli bağlantıyı sağlar. Yerel sertifika kalıcı birimde üretilir.
Veritabanı, kuyruk ve uygulama bilgisayar portlarına açılmaz.
Yalnız şifreli giriş `127.0.0.1` adresine bağlanır.
Kaynak ve bağlantı ayarı imaja kopyalanır.

Kurulum ayrı bir `fs-*` Compose projesi kullanır.
Çalışan 7400 yığını yeniden başlatılmaz.
Colima yeniden başlatılmaz.
Operatör sırları Git dışındaki izinli dosyada tutar.
Dosya yalnız sahibine okuma ve yazma izni verir.

Operatör aşağıdaki değişkenleri yerel ayar dosyasında tanımlar.

| Değişken | Anlamı |
| --- | --- |
| `PANE_PORT` | Yerel imajın ayırt edici sayısıdır. |
| `FS_STACK_IMAGE_TAG` | Kullanılacak yerel kiracı imajının etiketidir. |
| `FS_TENANT_WEB_PORT` | Yerel tanım için `8000` olur. |
| `FS_TENANT_SOCKET_PORT` | Kiracı ayarı için `9000` olur. |
| `AI_HTTPS_PORT` | Operatör boş bir yerel port seçer. |
| `MARIADB_ROOT_PASSWORD` | Yerel veritabanının sırrıdır. |
| `ADMIN_PASSWORD` | Yalnız yapay verili test sitesinin sırrıdır. |

Operatör bu komutları depo kökünde çalıştırır.
`$AI_ENV_FILE`, sırları içeren yerel dosyanın yoludur.

```bash
docker --context colima-factory compose --env-file "$AI_ENV_FILE" \
  -p fs-ai-service-local -f dev/ai-service/compose.yaml config --quiet
docker --context colima-factory compose --env-file "$AI_ENV_FILE" \
  -p fs-ai-service-local -f dev/ai-service/compose.yaml build
docker --context colima-factory compose --env-file "$AI_ENV_FILE" \
  -p fs-ai-service-local -f dev/ai-service/compose.yaml up -d --wait tenant-db tenant-redis
docker --context colima-factory compose --env-file "$AI_ENV_FILE" \
  -p fs-ai-service-local -f dev/ai-service/compose.yaml run --rm tenant-web \
  env/bin/python /workspace/dev/bootstrap.py test-platform-core.localhost --app platform_core
docker --context colima-factory compose --env-file "$AI_ENV_FILE" \
  -p fs-ai-service-local -f dev/ai-service/compose.yaml up -d --no-build
```

Yerel adres `https://test-platform-core.localhost` olur.
Operatör adrese seçtiği portu ekler.
Operatör istemciye yalnız bu testin sertifika otoritesini tanıtır.
Sertifika doğrulamasını kapatmak kabul ölçütünü karşılamaz.
Colima portu iletemezse operatör yalnız bu porta tünel açar.

## Model adını doğrulama

Model adı kodda veya Compose dosyasında sabitlenmez.
Yönetici model adını sağlayıcının güncel kaynağından doğrular.
Yönetici doğrulanan adı “PLT AI Model” kaydına girer.
API, uygulamaların konuştuğu program arayüzüdür.
Yönetici API kaydının izinli model listesini doldurur.

Boş izin listesi, aynı sağlayıcının kayıtlı modellerine izin verir.
Boş liste sağlayıcının güncel model kataloğunu doğrulamaz.
Yönetici kullanıma açmadan önce `platform_core.api.model.test_api` ucunu çağırır.
Bu çağrı kısa bir deneme gönderir. Sağlayıcı ücret isteyebilir.
Başarısız denemeden sonra yönetici yönlendirme kaydını etkinleştirmez.

`test_model_selection.py`, kayıt ve izin listesi denetimini sınar.
Olmayan model kaydı dış isteğe ulaşamaz.
Bu test gerçek sağlayıcı kataloğunun güncelliğini kanıtlamaz.

## Hüseyin Cengiz'in sunucu adımları

Bu adımlar canlıya geçiş yetkisi vermez.
Hüseyin Cengiz, dağıtım onayı alındığında adımları uygular.

1. Hüseyin Cengiz hedef Hetzner sunucusunu doğrular.
2. Hüseyin Cengiz veritabanı ve kuyruk birimlerinin konumunu doğrular.
3. Hüseyin Cengiz yedeklerin konumunu doğrular.
4. Hüseyin Cengiz üretim sertifikasını ve zincirini doğrular.
5. Hüseyin Cengiz model kaydını ve izin listesini doğrular.
6. Hüseyin Cengiz kısa model denemesini yapar.
7. Hüseyin Cengiz yetkisiz bağlam çağrısının reddedildiğini doğrular.
8. Hüseyin Cengiz önizlemesiz yazmanın reddedildiğini doğrular.

Üretim tanımı `deploy/` altında bulunur.
Bu yerel tanım üretim dağıtım betiğinin yerine geçmez.
Üretim doğrulamasında çalışan süreç, imaj özeti ve test sonucu kaydedilir.
Hüseyin Cengiz eski sürümü geri yükleme yolunu ayrıca doğrular.

## Veri sınırı

Saklanan model kullanım kayıtlarının hedefi Hetzner'dir.
Sunucu doğrulaması yapılmadığı için veri konumu henüz kanıtlanmadı.
Model geçidi konuşma içeriğini kullanım günlüğüne yazmaz.
Konuşma kimliğinin kendisi yerine özeti tutulur.
Ortak konuşma verisi kiracı veritabanına taşınmaz.
Ayrı konuşma deposunun Hetzner kurulumu açık iştir.

İzin verilen dış sağlayıcıya maskelenmiş içerik gidebilir.
Maskeleme, kişisel bilgi parçalarını gizleme işlemidir.
Saklama konumu ile dış sağlayıcıya aktarım ayrı denetlenir.
Bu dal hukuki aktarım onayı vermez.

## G-88 çağrı sözleşmesi

Bu bölüm hedef davranışı anlatır. Bu dal davranışı henüz uygulamaz.
İstemci, mevcut MCP çağrısının `_meta.page_context` alanını doldurur.
MCP, yapay zekânın araç çağırdığı iletişim biçimidir.
`doctype` kayıt türünü belirtir. `name` açık kayıt varsa kullanılır.
`selected_names` aynı türden en çok 200 farklı kayıt içerir.
Sunucu her kaydın okuma iznini denetler.
Bir kayıt yetkisizse sunucu bütün çağrıyı reddeder.
Sunucu ret sonucunu işlem günlüğüne yazar.
Sunucu doğruladığı bağlamı başarılı yanıtın `_meta.page_context` alanında döndürür.
Bağlam araç argümanlarını değiştirmez. Bağlam onay yerine geçmez.
Sayfa değişince istemci bağlamı yeniler.
Arayüzün bu alanı göndermesi kapsam dışı: atonota-web.

## Doğrulama kaydı

Gerçek komutlar ve sonuçlar bu dalın teslim kaydına yazılır.
Hetzner, gerçek sağlayıcı ve arayüz doğrulaması `not_run` durumundadır.
Gerçek okurla denenmedi.
