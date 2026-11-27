# Press kimlik testlerinin devri

Bu not AJA-70 işinin yerel test kapsamını açıklar.
Dal `pc/p1-identity-tests-press` adını taşır.
Geliştirici yalnız test ekledi. Uygulamanın davranışı değişmedi.
Yeni davranış olmadığı için önce düşen davranış testi `not_applicable` durumundadır.
Kiracı sitesi, bir kuruluşun ayrı uygulama sitesidir.
QA, testlerden sorumlu ajandır.

## Yerel kapsam

Beklenen sonuçlar `docs/contracts.md` dosyasından alındı.
Kimlik bağı, kuruluş üyeliği ve eşitleme kuralları esas alındı.
Kapanış ölçütleri, görevin verdiği faz raporundan okundu.

Yeni test dosyaları şunlardır:

- [Hesap akışı testleri](../../identity/identity_sync/tests/test_press_identity_lifecycle.py)
- [Kimlik ayarı testleri](../../identity/keycloak/tests/test_press_realm_drift.py)

Hesap testleri yerel HTTP sunucularıyla çalışır.
HTTP, servislerin istek ve yanıt yöntemidir.
Bu sunucular Keycloak, Press ve kiracı sitelerinin yerine geçer.
Testler gerçek Press veritabanını kullanmaz.
Kimlik ayarı testleri bellekte tutulan yönetim yanıtlarını kullanır.
Testler çalışan 7400 ortamını kullanmaz.

| Gereksinim | Eklenen kanıt | Açık kalan parça |
| --- | --- | --- |
| G-11 | Yeni test yoktur. Mevcut Press HTTP testleri sunucu ister. | QA izinli çağrıyı gerçek Press üzerinde denemelidir. QA yetkisiz belge türünü ve yabancı takım kaydını da sınamalıdır. |
| G-16 | Hesap akışı testleri daveti ve iki takımın kimlik bağını sınar. | Takım rolü, kaynak izni ve alt takım için gerçek Press kanıtı yoktur. |
| G-77 | Kimlik ayarı testleri ikinci kiracının istemcisini ve tam dönüş adreslerini sınar. | Takım üyeliğinin gerçek Press kaydından doğrulanması bekler. |
| G-79 | Hesap akışı testleri yeni ve mevcut hesabın davetini sınar. | QA gerçek Keycloak, Press ve kiracı hesaplarını birlikte sınamalıdır. |
| G-81 | Hesap akışı testleri kısmi hatayı, yeniden denemeyi ve tekrarlanan olayı sınar. | Gerçek olay eklentisiyle uçtan uca teslim kanıtı bekler. |
| G-152 | Kimlik ayarı testleri kayıtlı istemci ayarlarının düzeltilmesini sınar. | Tam ayar farkı taraması ve Keycloak yükseltme testi bekler. |

G-11 için mevcut dosyalar `test_auth_http.py` ve `test_request_guards.py` dosyalarıdır.
Bu dosyalar `apps/press_tr/tests/` klasöründedir.
G-16 rol ve alt takım eksikleri görevdeki durum raporunda kayıtlıdır.
Yeni testler bu eksikleri kapatmış sayılmaz.

Kendi kendine deneme hesabı açılması bu işin kapsamında değildir.
Bu sınır, görevin verdiği MVP kapsam kararından gelir.
MVP, ilk kullanılabilir sürümdür.

## Testlerin sınadığı sonuçlar

1. Yeni hesap, e-posta doğrulanmadan Press ve kiracı hesabı alamaz.
2. Doğrulanan hesap yalnız davet edildiği kiracıya bağlanır.
3. Mevcut hesap diğer takım üyeliğini ve kimliğini korur.
4. Üyelik reddedilirse sistem davet e-postası göndermez.
5. Bir kiracı geçici hata verirse diğer kiracı hesabı oluşur.
6. Yeniden deneme güncel kaynak bilgisini okur.
7. Tekrarlanan olay hedeflere yeni istek göndermez.
8. Kapatılan hesabın Press anahtarları ve takım üyelikleri kaldırılır.
9. Hatalı kiracı düzelince yeniden deneme hesabı kapatır.
10. Kayıtlı dönüş adresi, joker adresin yerine geçer.
11. Servis kapsamı varsayılan belirteçten çıkarılır.
12. İki kiracının istemcileri kendi adreslerini ve hedeflerini kullanır.

Belirteç, servisin istekte sunduğu kimlik bilgisidir.
Kapsam, bu kimlik bilgisinin hangi erişimi istediğini belirtir.
Joker adres, birden fazla dönüş adresini kabul eden tanımdır.

## Sunucu denemesinin sahibi ve sırası

Hüseyin Cengiz ayrı bir test ortamı hazırlar.
Bu devir canlı sunucuda işlem yapma yetkisi vermez.
A Takımı QA aşağıdaki denemeleri bu ortamda yürütür.
QA yalnız uydurma hesaplar ve ayrı test takımları kullanır.
Test kayıtlarında sır ve gerçek kişi verisi bulunmaz.

1. Hüseyin Cengiz ortamın kaynak commit'ini ve çalışan sürümlerini kaydeder.
2. QA izinli Press çağrısını kendi takımının kaydıyla dener.
3. QA aynı çağrıyı başka takımın kaydıyla dener.
4. QA yetkisiz belge türünün reddedildiğini doğrular.
5. QA takım rolleriyle alt takım sınırlarını dener.
6. QA yeni ve mevcut hesabı davet eder.
7. QA hesapları kimlik alanı ve kullanıcı kimliğiyle karşılaştırır.
8. QA üyelik kaldırmayı ve hesabı kapatmayı dener.
9. QA bir kiracıya erişimi test ortamında geçici keser.
10. QA başarısız olay kuyruğunu ve elle yeniden denemeyi doğrular.
11. QA aynı olayı tekrar gönderir ve kayıt sayısını karşılaştırır.
12. QA kayıtlı kimlik ayarlarıyla test ortamının ayarlarını karşılaştırır.
13. Hüseyin Cengiz Keycloak yükseltmesini ayrı test ortamında dener.
14. QA yükseltme sonrasında olay eklentisinin eşitlemesini doğrular.

Kabul için yabancı takım erişimi reddedilmelidir.
İzinli erişim çalışmalı ve yinelenen hesap oluşmamalıdır.
Başarılı yeniden denemeden sonra hata kuyruğu boşalmalıdır.
Onaysız ayar farkı ve eklenti uyumsuzluğu kalmamalıdır.
QA yanıt kodlarını ve kişisel veri içermeyen kayıt sayılarını saklar.

## Doğrulama kaydı

Geliştirici, 23 Kasım 2026 Pazartesi günü `backend` ucunu kendi dalına aldı.
Alınan commit `d54673d058a86b8af97f7589d3263060892461d1` değeridir.
İşlem yalnız `pc/p1-identity-tests-press` dalında yapıldı.
Bu değişiklik iki dosyaya toplam sekiz test ekler.
Uygulama kodu ve sözleşmeler değişmedi.

Paketin Python alt sınırı `3.11` değeridir.
Yerelde gözlenen Python sürümü `3.14.10` değeridir.
Paket ek bağımlılık bildirmez. Kilit dosyası sürümü uygulanabilir değildir.
Çalışan Keycloak ve Press sürümleri bu işte doğrulanmadı.

Kurallar 23 Kasım 2026 Pazartesi günü değişti. Artık kapı kilidi gerekmez.
Beş dal kapısını birleştirmede orkestratör koşar.
Bu yüzden ilk beş satır `not_run` durumundadır. Bu durum başarı anlamına gelmez.
Takım mimarı işin kendi testlerini 24 Kasım 2026 Salı günü yerelde koştu.

| Çalışma klasörü | Komut | Durum |
| --- | --- | --- |
| Dalın kökü | `dev/bin/module-boundaries` | `not_run` |
| Dalın kökü | `UV_OFFLINE=1 dev/bin/security-audit` | `not_run` |
| Dalın kökü | `dev/bin/ai-readiness` | `not_run` |
| Dalın kökü | `~/.local/bin/python3.14 -B -m unittest discover -s dev/tests` | `not_run` |
| Dalın kökü | `~/.local/bin/python3.14 -B -m unittest discover -s dev/naming/tests` | `not_run` |
| `identity/identity_sync` | `~/.local/bin/python3.14 -I -B -W error -m unittest discover -s tests -t . -p test_press_identity_lifecycle.py` | `pass`, 5 test |
| `identity/keycloak/tests` | `~/.local/bin/python3.14 -I -B -m unittest discover -s . -p test_press_realm_drift.py` | `pass`, 3 test |
| `identity/identity_sync` | `~/.local/bin/python3.14 -I -B -W error -m unittest discover -s tests -t .` | `pass`, 614 test, 23 atlandı |
| `identity/keycloak/tests` | `~/.local/bin/python3.14 -I -B -m unittest discover -s .` | `pass`, 238 test, 87 atlandı |
| Dalın kökü | `node ~/.claude/skills/coding-standards/scripts/yalin-turkce-denetim.mjs docs/handoff/press-identity-tests.md` | `pass`, 0 hata |

Atlanan testler canlı Keycloak gibi dış ortam ister.
İlk koşuda bir kimlik ayarı testi düştü.
Neden test yardımcısındaki sahte Keycloak sunucusuydu.
Sahte sunucu kapsam eşlemesini hep `aud-site-acme` adıyla arıyordu.
Bu yüzden ikinci kiracının isteği düşüyordu.
Düzeltme `test_create_tenant_client.py` dosyasındadır. Uygulama kodu değişmedi.

Dalı A Takımı QA bağımsız olarak incelemelidir.
Bağımsız QA incelemesi henüz yapılmadı.

Canlı ortam, gerçek Press ve Keycloak yükseltmesi `not_run` durumundadır.
Playwright, görevin açık kuralı gereği çalıştırılmadı.
Gerçek okurla denenmedi.
