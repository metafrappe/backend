# Oturum ve çağrı sınırlarının devri

Bu devir G-119, G-126 ve G-143 gereksinimlerini kapsar.
Sunucu adımlarının sahibi DevOps sorumlusudur.
Bu görev canlı sunucu ayarlarını değiştirmez.

## Çalışmanın durumu

Yerel testler 24 Kasım 2026 Salı günü geçti.
Beş dal kapısı da aynı gün geçti.
Sahip tablosuna durum sütunu eklendi.
Press sözleşmesindeki üç misafir çağrısı açık yetki kaydı aldı.
Bu kayıt `security: []` biçimindedir.
Kayıt testi önce bu eksiklerle düştü.
Sözleşme düzeltilince test geçti.

## Yerel testin sınırı

`e2e/tests/test_request_isolation.py` gerçek Frappe istek yolunu kullanır.
Test, oturum kayıtlarını bellekte tutar.
Test veritabanına ve Redis'e bağlanmaz.
Test oturum çerezini iki ayrı alan adıyla dener.
İzinli çağrının çalıştığını da denetler.
Bu test gerçek tarayıcı veya trafik yönlendirici kanıtı değildir.

G-119 için test, yabancı kaynağa erişim izni verilmediğini denetler.
Bu iznin HTTP başlığı `Access-Control-Allow-Origin` adını taşır.
Frappe bu okumaya 200 dönebilir.
Tarayıcı, izin başlığı yoksa yanıtı yabancı sayfaya açmaz.
Yazma isteğinde oturumun kayıtlı doğrulama anahtarı bulunur.
İstek bu anahtarı taşımazsa test 400 bekler.
Veritabanındaki oturum açılışı bu testin dışında kalır.

G-143 için test, liste dışı çağrıda 403 bekler.
Test eski çağrı yolunu ve iki API sürümünü kapsar.
API, uygulamaların sunucuya çağrı yaptığı bağlantıdır.
İzin listesi `platform_core/hooks.py` dosyasındaki `website_user_allowed_methods` kaydıdır.
Denetleyen kod `platform_core/shell/native_metadata.py` dosyasındadır.

G-126 için çağrı kaydı `contracts/` klasöründeki OpenAPI dosyalarıdır.
OpenAPI dosyası çağrının yolunu, yetkisini ve yanıtlarını tarif eder.
Sahip ve durum kaydı `docs/contracts.md` dosyasındadır.
`dev/ai_readiness/test_call_registry.py` kayıtsız çağrının kapıyı düşürdüğünü denetler.
Kapı, değişikliği kabul etmeden önce çalışan otomatik denetimdir.
Yeni test sözleşmenin sahibini ve durumunu da arar.
Yetki bildirimini ve hata açıklamasını denetler.
Test, bütün hata şemalarının doğruluğunu kanıtlamaz.
Mevcut kapı yalnız özel Frappe çağrılarının kayıt bütünlüğünü denetler.
`identity_sync` servisindeki kayıtsız HTTP uçlarının reddi bu kapsamda doğrulanmadı.
Bu eksik nedeniyle G-126 henüz tamamen kapanmaz.

Mimar AJA-117 görevinde yedi koşul koydu.
Test beş koşulu denetler:

1. Misafire açık çağrı sözleşmede `security: []` taşır. Ters yön de denetlenir.
2. Her özel çağrının en az bir hata yanıtı vardır.
3. Sahip tablosu her sözleşmeyi tam bir kez içerir.
4. Çağrının ad alanı sözleşmenin uygulamasıyla aynıdır.
5. Her sözleşmede `info.version` alanı doludur.

MCP çağrısı birinci koşulun istisnasıdır.
Frappe bu çağrıya misafiri alır.
Çağrı OAuth jetonunu kendi içinde denetler.

Üç koşul açık kalır:

1. Çağrı düzeyinde durum işareti yoktur.
2. Yama ile bağlanan iki Press çağrısının eşlemesi kayıtta yoktur.
3. Kapı zorunlu bir CI denetiminde koşmaz.

CI bağlantısı DevOps sorumlusunun işidir.

## Yerel komutlar

Komutları görev dalının kök klasöründe çalıştırın.
`TENANT_IMAGE` değişkenine mevcut yerel kiracı imajının adını verin.
Bu imaj Frappe 16 ve Python 3.14 içermelidir.
Komut imaj indirmez ve çalışan servisi değiştirmez.
Komut geçici konteynerin ağ bağlantısını kapatır.
Kaynak dosyalarını geçici konteynere kopyalar.
Test bitince geçici konteyner silinir.

```sh
~/.local/bin/python3.14 -B -m unittest discover \
  -s dev/ai_readiness -p test_call_registry.py -v
e2e/run-request-isolation "$TENANT_IMAGE"
```

Test, ana bilgisayarda Frappe yoksa atlanır.
Atlanan test geçerli kabul kanıtı değildir.
Yukarıdaki konteyner komutunun testleri çalıştırması gerekir.

## Hazırlık ortamındaki işler

DevOps sorumlusu aşağıdaki sırayla ilerler.

1. İki deneme kiracısı için ayrı alan adları hazırlayın.
2. Deneme alanlarında HTTPS bağlantısını açın.
3. Trafik yönlendiricisini doğru kiracıya bağlayın.
4. Bilinmeyen alan adından gelen isteği reddedin.
5. Kiracı çerezinin `Domain` alanı taşımadığını doğrulayın.
6. Çerezde `Secure`, `HttpOnly` ve `SameSite=Lax` değerlerini doğrulayın.
7. Birinci kiracının çerezini ikinci kiracıya göndermeyi tarayıcıyla deneyin.
8. Yabancı kaynaktan okuma ve ön istek gönderin.
9. Yabancı kaynağa erişim başlığı verilmediğini doğrulayın.
10. Anahtarsız yazma isteğinin 400 döndüğünü doğrulayın.
11. Liste dışı çağrının 403 döndüğünü doğrulayın.
12. İzinli okuma ve yazma akışlarını yeniden deneyin.

Yazma denemesinde yalnız uydurma test kaydı kullanın.
Gerçek kullanıcının oturumunu veya kaydını kullanmayın.
`ignore_csrf` ayarı kapalı olmalıdır.
`allow_cors` yalnız gerekli arayüz kaynaklarını içermelidir.
`allowed_referrers` yabancı kaynağı güvenilir saymamalıdır.
Bu ayarlar deneme öncesinde ve sonrasında kayda alınmalıdır.
Kayıtta gizli değer bulunmamalıdır.

Trafik yönlendiricisindeki engel, uygulamanın izin denetimini kaldırmaz.
Çağrı yolları arasında aynı ret davranışı korunmalıdır.
Başarısız ayarın geri dönüşünü DevOps sorumlusu önce deneme ortamında hazırlar.
Geri dönüş, önceki onaylı ayar dosyasını geri yükler.
Geri dönüşten sonra aynı kabul denemeleri yeniden çalışır.

## Kabul kaydı

DevOps sorumlusu alan adlarını ve test tarihini kayda yazar.
Gerçek tarayıcının adını ve sürümünü de yazar.
Her denemede istek yolunu ve yanıt kodunu kaydeder.
Çerez ve anahtar değerlerini kayda yazmaz.
G-119 ve G-143 ancak sunucu kanıtıyla tamamen kapanır.

Gerçek tarayıcı ve sunucu denemeleri henüz çalıştırılmadı: `not_run`.
Gerçek okurla denenmedi.
