# Kimlik ekranı testlerinin devri

Bu belge AJA-74 görevinin yerel kanıtını ve açık parçalarını kaydeder.
Dal `pc/aja74-identity-tests` adını taşır.
Testler önce eski depodaki `pc/p1-identity-tests-ui` dalında yazıldı.
Eski dalın son commit'i `f2179600404285556b252abedd225706a4493858` değeridir.
Dosyalar 27 Kasım 2026 Cuma günü bu depoya taşındı.

## Gereksinim sınırı

| Kayıt | Eklenen test | Açık parça |
| --- | --- | --- |
| G-80 | `identity/keycloak/themes/atonota/test/tests/identity-safety.spec.ts` giriş ve kurtarma ekranlarını sınar. Test Türkçe metni, klavye geçişini ve en az 14 CSS px yazıyı denetler. | Keycloak sürüm yükseltmesi denenmedi. İki sürüm arasında geçiş kanıtı gerekir. |
| G-132 | `apps/platform_core/platform_core/identity/tests/test_url_privacy.py` backend adreslerini sınar. Tarayıcı testi de uydurma e-posta, telefon ve kimlik numarası kullanır. | Ekran, filtre ve kayıt yönlendirmesinin okuma yetkisi için kapsam dışı: atonota-web. Kalıcı vekil kayıt kimliği ayrı bir backend işidir. |
| G-145 | Tarayıcı testi üç zararlı içerik örneğini sınar. Örnekler `script`, SVG olay kodu ve görsel olay kodudur. Test, yanıtın içeriği güvenli metne çevirdiğini doğrular. | Yazdırma önizlemesi için kapsam dışı: atonota-web. Güvenlik başlıkları DevOps sorumlusunun kapsamındadır. |

Bu görev üç gereksinimi bütünüyle kapatmaz.
Depo yalnız Keycloak `26.8.2` sürümünü sabitler.
Yükseltmenin başlangıç ve hedef sürümleri tanımlı değildir.
Bu yüzden sürüm yükseltmesi açık kalır.

G-132 sınırını Sistem Mimarı AJA-81 görevinde değerlendirdi.
Karar, proje kaydındaki O-70 maddesindedir.
Backend, giriş sonrası dönüş yolunu çağıran ekrandan alır.
Backend, giriş tamamlanınca bu yolu aynen döndürür.
Testler, kişisel dönüş yolunun Keycloak giriş adresine taşınmadığını doğrular.
Testler, kullanıcının son dönüş adresinin kişisel veri taşımadığını kanıtlamaz.

Testler mevcut davranışı kapsar. Uygulama kodu değişmedi.
Bu yüzden önce başarısız test kanıtı yoktur.
Backend testi gerçek adres kurucularını çağırır.
Önbellek, oturum, ayarlar ve belirteç doğrulaması testte taklit edilir.
Bu test gerçek HTTP yetkilendirmesini veya belirteç doğrulamasını kanıtlamaz.

## Backend testini çalıştırma

Test site ve veri tabanı istemez. Test, hazır Frappe imajında ağsız bir kapta koşar.
Depo kökünde şu komutu çalıştırın:

```bash
tar -cf - apps/platform_core libs/oidc_verify |
  docker --context colima-factory run --rm -i --network none \
    --read-only --tmpfs /tmp --entrypoint /bin/bash \
    fs-tenant-dev:<etiket> -c \
    'tar -xf - -C /tmp &&
     PYTHONPATH=/tmp/apps/platform_core:/tmp/libs/oidc_verify \
     env/bin/python -B -m unittest -v platform_core.identity.tests.test_url_privacy'
```

`<etiket>` yerine yerel `fs-tenant-dev` imajlarından birini yazın.
Komutu ortak test kilidiyle çalıştırın:
`/usr/bin/lockf -k -s -t 600 ~/.cache/frappesetup-test-kilidi/yer-1 <komut>`.

## Tema testini çalıştırma

Tema testi Keycloak ve Mailpit kaplarını ister.
Adımlar tema belgesinin "Testler" bölümündedir: `identity/keycloak/themes/atonota/README.md`.
Testi yalnız şu iki projede koşun: `chromium-320` ve `webkit-desktop`.
Firefox testi koşulmaz.
Koşudan sonra `theme-dev.sh down` ile ortamı kapatın.

Bu depoda `package.json` dosyası yoktur.
Bu yüzden `@playwright/test` paketi ve tarayıcılar önce kurulmalıdır.

## Kalan doğrulama

| Kontrol | Durum | Neden |
| --- | --- | --- |
| `identity-safety.spec.ts` | `not_run` | Ayrıntı AJA-74 görevinin teslim yorumundadır. |
| Keycloak sürüm yükseltmesi | `not_run` | İkinci sürüm tanımlı değildir. |
| Gerçek Safari ve gerçek telefon | `not_run` | WebKit denemesi gerçek cihaz denemesi değildir. |
| Firefox | `not_applicable` | Kullanıcı bu testleri yasakladı. |
| CI | `not_run` | Depoda CI yok. CI kurulumu AJA-1528 işindedir. |

Gerçek okurla denenmedi.
