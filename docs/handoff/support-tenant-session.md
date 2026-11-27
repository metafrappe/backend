# Kiracı destek oturumu

Bu belge AJA-177 işini anlatır.
Gereksinim kimliği G-18 olur.
Dal `pc/support-tenant-session` adını taşır.
Kararlar O-65 ve O-66 olur.
AJA-245 işi HTTP testlerini düzeltti.
Son güncelleme 24 Kasım 2026 Salı günü yapıldı.

## Ne yapıldı

Destek çalışanı müşteri sitesinde sınırlı bir oturum açabilir.
Bu oturum müşterinin onayına bağlıdır.
Kiracı, müşterinin kendi Frappe sitesidir.
Press, siteleri yöneten merkezi sistemdir.

Oturum şu sırayla açılır:

1. Destek çalışanı Press'te `open_tenant_session` ucunu çağırır.
2. Press onayı yeniden denetler.
3. Press açılışı gerekçesiyle yorum kaydına yazar.
4. Press tek kullanımlık bir bilet verir. Bilet 60 saniye geçerlidir.
5. Çalışan bileti kiracı sitesine götürür.
6. Kiracı, `start_support_session` ucunda bileti Press'e sorar.
7. Press bileti siler ve onayı yeniden denetler.
8. Press kiracıya o siteye bağlı bir oturum anahtarı verir.
9. Kiracı, ayarlardaki destek kullanıcısıyla oturum açar.

Bilet yalnız bir kez kullanılır.
Press bilette ve anahtarda yalnız SHA-256 özetini saklar.
SHA-256, bir değerin geri çevrilemeyen özetidir.
Oturum anahtarı tarayıcıya hiç gitmez.

## Her istekte denetim

Kiracı, destek kullanıcısının her isteğini Press'e sorar.
Press şu koşulları her seferinde yeniden denetler:

- Onay hâlâ “Accepted” durumundadır.
- Onayın süresi bitmemiştir.
- Müşteri onayı geri almamıştır.
- Site hâlâ aynı müşteriye aittir.
- Çalışan hâlâ destek rolünü taşır.
- Anahtar bu siteye bağlıdır.

Bir koşul tutmazsa kiracı oturumu siler.
Sonra kiracı isteğe 403 döner.
Press'e ulaşılamazsa da sonuç aynıdır.
Kiracı ayrıca onayın kalan süresini kendisi tutar.
Süre bitince kiracı Press'e sormadan oturumu kapatır.

Kiracı bu denetimi kimlik kancası olarak yapar.
Kimlik kancası, Frappe'nin isteğin kullanıcısını belirlediği adımdır.
Denetim diğer kimlik kancalarından sonra çalışır.
Böylece denetim her isteğin son kullanıcısını görür.

Destek kullanıcısı yalnız tarayıcı çereziyle çalışabilir.
`Authorization` başlığı taşıyan istek 403 alır.
Bu kural API anahtarını ve ajan jetonunu da kapsar.
Destek kullanıcısı anlık bildirim bağlantısı da açamaz.
Açık bir bağlantı, onay bittikten sonra da veri alabilirdi.
Bu yüzden `frappe.realtime.get_user_info` isteği 403 alır.

Press her istekteki denetimde satır kilidi almaz.
Kilitsiz okuma, Press'in site kaydını meşgul etmez.
Bilet verme ve bileti anahtara çevirme kilitle yapılır.

## Yönetici oturumu

Destek oturumu yönetici oturumu değildir.
Kiracı destek kullanıcısını `support_session_user` ayarından okur.
Bu kullanıcı `Administrator` olamaz.
Kullanıcı `System Manager` ya da `Administrator` rolünü taşıyamaz.
Kullanıcı kapalıysa oturum açılmaz.
Kiracı rolleri her istekte yeniden denetler.
Kullanıcıya sonradan yönetici rolü verilirse oturum kapanır.
Yönetici onayı bu yoldan oturum açmaz.
Yönetici oturumu ayrı bir iştir. Bu dal o işi yapmaz.

## Kiracı ayarları

Kiracı sitesinin ayarında iki değer bulunmalıdır:

- `support_press_url` değeri Press'in özel ağdaki `https` adresini tutar.
- `support_session_user` değeri kiracıda var olan sınırlı bir kullanıcıyı tutar.

Ayar yoksa oturum açılmaz.
Destek kullanıcısının yetkisi kiracıdaki rolleriyle sınırlıdır.
O-66 kararına göre bu rolleri müşteri seçer.
Destek kullanıcısına varsayılan rol verilmez.
Bu dal rol seçmez ve kullanıcı oluşturmaz.

## Güvenlik kaydı

Semgrep, kodda güvenlik kalıbı arayan bir araçtır.
Press'in iki misafir ucu için Semgrep onayı yazıldı.
Onaylar `backend/dev/security/semgrep-exceptions.json` dosyasındadır.
`tenant_session.py` dosyası onay listesine eklendi.
İki kapsamın özeti `--snapshot` komutuyla yenilendi.
Misafir uçları hız sınırı taşır.
Bilet ucu dakikada 30 isteğe izin verir.
Denetim ucu dakikada 1200 isteğe izin verir.
Bir kiracı sunucusu destek kullanıcısının her isteğini sorar.
Bu yüzden denetim ucunun sınırı yüksektir.

## Uçlar

| Uç | Yer | İşlem |
| --- | --- | --- |
| `press_tr.api.support.open_tenant_session` | Press | Destek çalışanı bilet alır. |
| `press_tr.api.support.redeem_tenant_session` | Press | Kiracı bileti bir kez anahtara çevirir. |
| `press_tr.api.support.check_tenant_session` | Press | Kiracı her istekte onayı sorar. |
| `platform_core.api.auth.start_support_session` | Kiracı | Çalışan bileti verir ve oturum açar. |

Press'teki son iki uç oturum istemez.
Bu iki ucu yalnız kiracı sunucusu çağırır.
Bu uçlar O-55 kararı gereği özel ağda kalır.
Bilet ve anahtar 256 bit rastgele değerdir.
Uçlar Press'in misafir izin listesine eklendi.

Sözleşmeler şu dosyalardadır:

- `backend/contracts/press_tr-support.openapi.yaml`
- `backend/contracts/platform_core-identity.openapi.yaml`

## Kabul ölçütleri ve testler

Önce testler yazıldı. Testler kod olmadan düştü.
Press testlerinde ilk 17 testin hepsi düştü.
Kiracı testlerinde ilk 19 testin hepsi düştü.
İnceleme sonrası eklenen altı test de önce düştü.
Sonra kod yazıldı ve testler geçti.

| Ölçüt | Press testi | Kiracı testi |
| --- | --- | --- |
| 1. Geçerli onayla açılır | `test_valid_consent_opens_a_ticket_and_audits_the_reason` | `test_valid_ticket_opens_a_session_for_the_support_user` |
| 2. Onay yoksa 403 | `test_missing_or_invalid_consent_opens_nothing` | `test_press_refusal_opens_no_session` |
| 3. Başka site açılmaz | `test_ticket_cannot_open_another_site` | `test_grant_for_another_site_is_refused` |
| 4. Süre bitince 403 | `test_expired_consent_ends_an_open_session` | `test_expired_consent_ends_the_open_session` |
| 5. Geri alınınca 403 | `test_revoked_consent_ends_an_open_session` | `test_revoked_consent_ends_the_open_session` |
| 6. Yönetici oturumu değil | `test_administrator_consent_does_not_open_a_support_session` | `test_support_user_with_administrator_roles_is_refused` |
| 7. Açılış gerekçeyle yazılır | `test_valid_consent_opens_a_ticket_and_audits_the_reason` | Yok |

Testler Frappe'nin yerine sahte nesneler kullanır.
Bu testler gerçek veritabanına ve ağa bağlanmaz.

Frappe ortamı isteyen HTTP testleri de yazıldı:

- `press_tr/api/test_support.py` dosyasına sekiz test eklendi.
- `platform_core/api/test_auth.py` dosyasına iki test eklendi.

Bu on test yerelde çalıştırılmadı.

## AJA-245 test düzeltmesi

QA, AJA-178 görevinde altı HTTP testinin düştüğünü buldu.
Hata test dosyasındaydı. Üretim kodu değişmedi.

1. `_tenant_exchange` yardımcısı artık `Content-Type: application/json` başlığını gönderir.
   Bu başlık olmadan Frappe JSON gövdeyi okumaz. Sunucu 500 döner.
2. Süre bitimi ve onay iptali artık iki ayrı testtir.
   Testlerin adları `test_tenant_session_ends_when_consent_is_revoked` ve `test_tenant_session_ends_when_consent_expires` olur.
   Her test kendi istek IP adresini alır. Böylece giriş sayısı hız sınırına takılmaz.
3. İki test, onaydan önce denetimin 200 döndüğünü de doğrular.

## Bağımsız inceleme

Ayrı bir inceleme ajanı kodu salt okunur inceledi.
İnceleme bir engelleyici, iki önemli ve üç küçük bulgu verdi.
Her bulgu için önce düşen test yazıldı. Sonra kod düzeltildi.

1. Başlıkla gelen istek denetimden kaçıyordu. Denetim kimlik kancasına taşındı.
2. Açık anlık bildirim bağlantısı veri almaya devam edebilirdi. Bağlantı kapatıldı.
3. Press her denetimde satır kilidi alıyordu. Denetim kilitsiz okur.
4. Yarım kalan Press yanıtı 500 hatası veriyordu. Artık 403 verir.
5. Yönetici rolü yalnız açılışta denetleniyordu. Artık her istekte denetlenir.
6. Önbellek hatası 500 hatası veriyordu. Artık 403 verir.

İnceleme gerçek anlık bildirim sunucusunu okumadı.

## Kapanmayan işler

Gerçek kiracı ağıyla deneme yapılmadı.
Bu deneme ayrı bir yerel Press ve kiracı ortamı ister.
QA bu denemeyi kendi ortamında yapmalıdır.

Şu kontroller `not_run` durumundadır:

- Gerçek Press ve kiracı arasında HTTP isteği.
- Yukarıdaki on HTTP testi. Bu testler ayrı bir yerel Press ortamı ve kapı kilidi ister.
- `test_machine_routes.py` testi. Bu test Frappe ortamı ister. Test, yeni misafir uçlarını içerecek biçimde güncellendi.
- `test_contract_gate.py` testi. Bu test de Frappe ortamı ister.
- Gerçek tarayıcı denemesi.
- Altı dal kapısı. Orkestratör bu kapıları birleştirmede koşar.

A Takımı PO iki ürün sorusunu karara bağladı. Karar O-66 olur.

- Destek kullanıcısına kiracıda varsayılan rol verilmez. Rolleri müşteri seçer.
- `System Manager` ve `Administrator` rolleri her zaman yasaktır.
- Her istekte Press'e sormanın hız etkisi G-18 için engel değildir. Ölçüm MVP sonrasına kalır.

Şu iş hâlâ ürün kararı ister:

- Yönetici oturumunun ayrı akışı.

Bozuk gövdeli isteğe misafir uçlar 500 döner. Bu, Frappe'nin varsayılanıdır. PO kararıyla bu işte değişmedi.

## Testi yeniden çalıştırma

Komutlar depo kökünde çalışır:

```sh
~/.local/bin/python3.14 -B -m unittest discover -s backend/apps/press_tr/tests -p 'test_support_*.py'
~/.local/bin/python3.14 -B -m unittest discover -s backend/apps/platform_core/platform_core/identity/tests -p 'test_support_session.py'
```

Bu belge canlı sunucuyu değiştirme yetkisi vermez.
Bu belge dağıtım veya genel ağ erişimi onayı vermez.
Gerçek okurla denenmedi.
