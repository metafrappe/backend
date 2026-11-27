# G-149 sunucu süresi, kullanıcı ölçümü ve yük deneyi

Bu not canlı adımları anlatır. Adımları kıdemli DevOps mühendisi Hüseyin Cengiz uygular.
Adımlar önce yetkili deneme ortamında denenir. Canlı sunucuda deneme ayrı onayla başlar.

## Depoda ne var

- Her sunucu yanıtı `Server-Timing` başlığını taşır. Başlığın değeri `app;dur=<milisaniye>` biçimindedir.
- Başlıkta yalnız ölçü adı ve süre vardır. Başlık sayfa adresini ya da kişi adını taşımaz.
- Kod `apps/platform_core/platform_core/observability/server_timing.py` dosyasındadır.
- Tarayıcı ölçümleri tek bir uca gelir. Uç `platform_core.api.observability.collect_rum` adını taşır.
- Uç yalnız sayfa yolu şablonunu ve ölçüm değerlerini kabul eder. Örnek şablon `/panel/leave-application/:name` biçimindedir.
- Uç kişi bilgisini kaydetmez. Kullanıcı adı, IP adresi ve tarayıcı adı kayda girmez.
- Uç başka bir alan görürse isteği reddeder. Örneğin `email` alanı gelirse istek reddedilir.
- Uç her kaydı sitenin `logs/platform_core.rum.log` dosyasına bir JSON satırı olarak yazar.
- Uç sözleşmesi `contracts/platform_core-observability.openapi.yaml` dosyasındadır.
- Yük deneyi betiği `dev/load/load_trial.py` dosyasıdır. Betik yalnız Python'un kendi parçalarını kullanır.

## Yük deneyi betiği

Betik yalnız yerel adrese istek gönderir. Kabul ettiği adresler `localhost`, `127.0.0.1`, `::1` ve `*.localhost` adresleridir.
Betik başka bir adres görürse 2 koduyla durur. Bu kural canlı sunucuya yanlışlıkla yük gitmesini önler.

Betik her yol için şu değerleri yazar:

- istek sayısı ve hata sayısı,
- istemcide ölçülen p50, p75 ve p95 süreleri,
- `Server-Timing` başlığından okunan p50, p75 ve p95 süreleri,
- başlığı olmayan yanıtların sayısı.

Bu sayılar bir deneyin sonucudur. Sayılar ölçülmüş kapasite ya da ürün sözü değildir.

## Yerel deneme sonucu

Yerel deneme 28 Kasım 2026 Cumartesi günü yapıldı. Ortam geliştirme Mac'indeki `fs-dev-ortam` yığınıydı.
Sitede ERPNext ve Platform Core kuruluydu. Her yola 30 istek gitti. Aynı anda 4 istek koştu.

| Yol | Hata | İstemci p95 | Sunucu p95 |
| --- | --- | --- | --- |
| `/api/method/ping` | 0 | 10,7 ms | 3,9 ms |
| `/login` | 0 | 379,9 ms | 381,4 ms |

Her yanıtta `Server-Timing` başlığı vardı. Bu sonuç yalnız betiğin çalıştığını gösterir. Sonuç canlı kapasiteyi göstermez.

## Canlı adımlar

### 1. Başlığın vekil sunucudan geçtiğini doğrulayın

1. Deneme sitesine bir istek gönderin. Örneğin `curl -sI https://<deneme-sitesi>/api/method/ping` komutunu koşun.
2. Yanıtta `Server-Timing` satırını arayın.
3. Satır yoksa vekil sunucu başlığı siliyor olabilir. Bu durumda vekil sunucunun ayarını düzeltin.

### 2. RUM günlüğünü Grafana'ya bağlayın

1. Her sitenin `logs/platform_core.rum.log` dosyasını günlük toplayıcıya ekleyin.
2. Grafana'da p75 ve p95 panellerini sayfa yolu şablonuna göre kurun.
3. Günlük dosyası en çok 100.000 bayt büyür. Frappe dosyayı sonra döndürür ve 20 eski dosya tutar.

### 3. Canlıda yük deneyi

Bu betik canlı adrese bilerek istek göndermez. Canlı yük deneyi için ayrı bir araç gerekir.
G-149 bu iş için k6 aracını anar. k6 bu Mac'te kurulu değildir.

1. Hüseyin Cengiz deneyi yalnız deneme sitesinde koşar. Gerçek müşteri sitesinde koşmaz.
2. Deneme sitesinde yalnız uydurma örnek veri bulunur.
3. Deneyden önce ekip PO'su ve proje sahibi onay verir.
4. Senaryolar gerçek kullanıcı yolculuklarından seçilir. Örneğin giriş, panel açılışı ve izin listesi seçilebilir.
5. Hüseyin Cengiz sonucu önce ve sonra ölçümüyle göreve yazar.

## Açık işler

- Panel ve giriş sayfası henüz ölçüm göndermiyor. Tarayıcı tarafı ayrı bir ön yüz işidir.
- Tarayıcı oturum açıksa `X-Frappe-CSRF-Token` başlığını gönderir. Bu yüzden `fetch` ile `keepalive: true` kullanılır. `navigator.sendBeacon` başlık gönderemez.
- MariaDB yavaş sorgu günlüğü ve RQ kuyruk bekleme süresi bu işte yoktur. Bu ölçümler sunucu ayarıdır.
