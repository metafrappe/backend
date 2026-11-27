# Operatör kimliği ve personel yetkileri

Bu çalışma SA-1, SA-2 ve SA-3 maddelerinin yerel kodunu hazırlar.
Canlı kurulum bu çalışmanın dışında kalır.

## Uygulama planı

1. Kimlik modülleri, doğrulanmış belirteçten operatör rollerini ayırır.
2. Press kimlik modülü, kayıtlı insan hesabını bulur.
3. Press kimlik modülü, personel rollerini eşler.
4. Press istek kancası, servis hesabının insan rolünü reddeder.
5. Press istek kancası, normal kullanıcının doğrudan mali değişikliğini reddeder.
6. Operasyon sitesinin kimlik modülü, personel rollerini eşler.
7. Operasyon sitesi, ilk destek girişinde destek görevlisi kaydını açar.

Belirteç, giriş sunucusunun imzaladığı kimlik bilgisidir.
Kod, imza doğrulamasından sonra grup ve rol bilgisini kullanır.
Mevcut giriş akışı tarayıcı bağını ve tek kullanımlık kodu doğrular.
Bu çalışma aynı giriş akışını kullanır.

Kayıt sahipleri Press kimlik modülü ve platform kimlik modülüdür.
İki modül yalnız ortak belirteç kitaplığına bağlanır.
Modüller birbirinin kodunu çağırmaz.
Mevcut User kaydı ve kimlik bağı hesap bilgisini tutar.
Destek görevlisi kaydını Helpdesk uygulaması tutar.
Kod yeni hesap açmaz. Yetkili kurulum, insan hesabını önceden hazırlar.
Kod gizli anahtar üretmez. Anahtar teslimini altyapı sorumlusu yapar.

## Kalan doğrulama

Gerçek Keycloak girişi henüz denenmedi.
Canlı Press ve operasyon sitesi henüz denenmedi.
Gerçek okurla denenmedi.

## Yerel kaynak kanıtı

Kaynak okuması çalışan yerel 7400 ortamından yapıldı.
Ortam yeniden başlatılmadı. Uygulama verisi değiştirilmedi.
Press ortamında Frappe sürümü 16.50.0 olarak okundu.
Manifest Frappe 16 serisini destekler.
Press paketindeki sürüm metni 0.7.0 değeridir.
Git etiketi ayrıca v0.154.1 olarak doğrulandı.
Git kaydı `7a4384d5eec9f0f0dce4124e9dd48b106e51222f` değeridir.
Çalışan Python sürümü 3.14.10 olarak okundu.

`frappe/auth.py:629`, kimlik doğrulamadan sonra kimlik kancalarını çalıştırır.
`frappe/auth.py:695`, kişisel API anahtarıyla kullanıcıyı belirler.
`press/api/client.py:126`, destek rolünün takım süzmesini atlayabildiğini gösterir.
`frappe/model/document.py:1394`, kayıt olaylarının hangi sırada çalıştığını gösterir.
`frappe/utils/logger.py:38`, istek gövdesini ekleme seçeneğini gösterir.
Denetim kaydı bu seçeneği kapalı kullanmalıdır.

## Canlı kurulumun sahibi

DevOps sorumlusu gizli anahtar yönetimini ve sunucu kurulumunu yapar.
DevOps sorumlusu her insan için ayrı hesap hazırlar.
DevOps sorumlusu servis hesaplarını ayrı tutar.
DevOps sorumlusu anahtarları depoya ve görev yorumuna yazmaz.
QA, hazırlık ortamında izin verilen ve reddedilen işlemleri sınar.
Canlıya geçiş kararı, yerel test sonucundan ayrı tutulur.

## Kabul için gereken canlı kanıt

1. QA, iki operatörün ayrı hesaplarla işlem yaptığını gösterir.
2. QA, işlem kaydındaki hesap adlarını karşılaştırır.
3. QA, servis hesabına insan rolü verilmesini dener.
4. QA, normal kullanıcının mali kayıt değişikliğini dener.
5. QA, destek isteğinin denetim kaydını gösterir.
6. QA, Keycloak grubuyla personel rollerinin eşleştiğini gösterir.
7. QA, ilk destek girişinde tek görevli kaydı oluştuğunu gösterir.
8. QA, rol kaldırılınca yeniden girişin yetkiyi kaldırdığını gösterir.
9. QA, kayıtlarda gizli anahtar bulunmadığını denetler.

DevOps sorumlusu bu denemeleri yalnız hazırlık ortamında yürütür.
Bu belge canlı sunucuyu değiştirme izni vermez.

## Kurulum sözleşmesi

Press, `press_operator_accounts` ayarından izinli insan hesaplarını okur.
Her hesabın değeri `issuer` ve `subject` alanlarını taşır.
`issuer`, Keycloak sunucusunu ve realm adresini belirtir.
`subject`, kişinin Keycloak kimliğidir.
Mevcut `PTR Identity Link` kaydı aynı kişiyi göstermelidir.
İnsan hesabının türü `System User` olmalıdır.
Bu ayarlar gizli anahtar taşımaz.

Press, `press_service_users` ayarında servis hesaplarının adlarını tutar.
Servis hesabı yalnız `Press Service` rolünü alabilir.
Frappe'nin ortak `All` ve `Guest` rolleri bu sınırın dışındadır.
Servis hesabı insan hesabı listesine giremez.
Bu çalışma servis hesabına mali yazma izni vermez.

Personel belirteci `/platform-operator` grubunu tam adıyla taşımalıdır.
Grup adının benzeri kabul edilmez.
Personel belirteci `realm_access.roles` alanında görev rolünü taşımalıdır.
Press eşlemesi aşağıdaki gibidir.

| Keycloak rolü | Press rolü |
| --- | --- |
| `ops-billing` | `Press Ops Billing` |
| `ops-finance` | `Press Ops Billing` |
| `ops-support` | `Press Support Agent` |
| `ops-admin` | `Press Ops Admin` |

`Press Ops Admin` rolü sınırsız yönetici yetkisi taşımaz.
Mimar bu turda ek izin verilmemesini kararlaştırdı.
Fatura rolü mali kayıtlarda okuma, oluşturma, değiştirme ve onay izni alır.
Fatura rolü ödeme ertelemesinde okuma, oluşturma ve değiştirme izni alır.
Fatura rolü Team kaydında yalnız okuma ve seçme izni alır.
Kurulum ve güncelleme kancaları izinleri tekrar uygulanabilir biçimde yazar.
Diğer rollerin özel izin satırları korunur.

Operasyon sitesi `platform_staff_login` ayarıyla personel girişini açar.
Ayarın değeri `true` veya `1` olur.
`platform_staff_accounts` ayarı izinli hesapları aynı kimlik alanlarıyla tutar.
Mevcut `PLT Identity Link` kaydı önceden hazırlanmalıdır.
Personel kendi e-posta bilgisiyle yeni bağ kuramaz.
Personel kendi e-posta bilgisiyle hesap açamaz.
Mevcut Keycloak sağlayıcı kaydı `sign_ups=Deny` kuralını korur.
Yerleşik sosyal giriş yolu kapalı kalır.
Uygulamanın tarayıcı bağını doğrulayan giriş yolu kullanılır.

## Mimarın kararı

AJA-197 görevi rol eşlemesini netleştirdi.
Operasyon sitesinde destek rolünün adı `Agent` olur.
`HD Agent` destek görevlisinin kayıt türüdür.
DevOps sorumlusu, Helpdesk sürümünü tam Git kaydıyla sabitler.
Sürüm operasyon sitesinin imaj kilidine girer.
Sürüm sabitlenmeden destek girişi açılmaz.
İlk girişte sistem, Helpdesk kayıt kodunu çağırır.
Bu kod `Agent` rolünü de verir.
Tekrar girişte ikinci görevli kaydı oluşmaz.
Destek rolü kalkınca görevli kaydı pasif olur.
Sistem, `Agent` rolünü de kaldırır.

Press koruması, genel yazma uçlarında uygulanır.
Kayıt olayında bütün mali yazıları engelleyen kanca kullanılmaz.
Press'in iç faturalama akışı kendi izin denetimini korur.
Normal kullanıcı genel uçlarla mali kayıtları değiştiremez.
Tek bir istisna vardır. Müşteri kendi faturasının ödeme bağlantısını açabilir.
Pano bunun için `press.api.client.run_doc_method` ucunu çağırır.
İstisna yalnız `Invoice` kaydındaki `stripe_payment_url` yöntemini kapsar.
Bu yöntem faturayı değiştirmez. Faturanın sahibini Press kendisi denetler.
Paylaşım bu yasağı kaldıramaz.

## Press kaynak çağrıları

Bu liste `7a4384d5eec9f0f0dce4124e9dd48b106e51222f` kaydından çıkarıldı.
Kaynak, çalışan yerel Press container içinden okundu.
Aşağıdaki çağrılar izin denetimini atlayan seçenek taşımaz.

| Dosya | Satır | Çağrı ve gerekçe |
| --- | --- | --- |
| `press/doctype/team/team.py` | 1668 | `create_upcoming_invoice`, faturayı `insert()` ile açar. |
| `press/doctype/team/team.py` | 1910 | Fatura oluşturma `invoice.insert()` çağrısını kullanır. |
| `saas/doctype/saas_app_subscription/saas_app_subscription.py` | 268 | Abonelik faturası `invoice.submit()` çağrısını kullanır. |
| `saas/doctype/saas_app_subscription/saas_app_subscription.py` | 303 | Abonelik faturası `invoice.insert()` çağrısını kullanır. |
| `press/doctype/invoice/invoice.py` | 1140 | Kredi dağılımı mevcut kaydı `save()` ile değiştirir. |
| `press/doctype/invoice/invoice.py` | 1143 | Faturaya kredi uygulama, bakiye kaydını `insert()` ile açar. |
| `press/doctype/invoice/invoice.py` | 1150 | Kredi uygulama, bakiye kaydını `submit()` ile onaylar. |
| `press/doctype/invoice/invoice.py` | 1172 | Sonraki dönem faturası `insert()` ile açılır. |
| `api/billing.py` | 1272 | Ödeme bildirimi bakiye kaydını `submit()` ile onaylar. |
| `api/billing.py` | 1301 | Ödeme bildirimi faturayı `submit()` ile onaylar. |

Bu çağrılar oluşturma, değiştirme ve onay izinlerini gerektirir.
Kod bu izinleri topluca kaldırmaz.
Genel yazma uçlarındaki koruma, müşterinin doğrudan değişikliğini reddeder.
Gerçek takım kaydı, abonelik ve ödeme bildirimi testleri hâlâ gerekir.
Kaynak incelemesi bu testlerin yerine geçmez.

## Yerel denetim

İlk test koşusunda 8 Press testi başarısız oldu.
İlk test koşusunda 5 personel testi başarısız oldu.
İki yeni kod dosyası henüz yoktu.
Sonraki ret testleri hesap türünü ve kimlik bağını ayrıca sınadı.
Bu iki test önce başarısız oldu. Kod düzeltildikten sonra geçti.
Destek kaydının zorunlu ad alanı da önce başarısız testle doğrulandı.

Son hedefli koşuda 16 operatör testi ve 12 mali giriş testi geçti.
Ayrıca 9 personel testi geçti.
Sayısal dosya hedefleri için test önce 13 alt durumda başarısız oldu.
Düzeltmeden sonra tüm alt durumlar geçti.
Testler sahte Frappe nesnelerini kullanır.
Bu sonuç gerçek HTTP girişi kanıtı değildir.
Gerçek Press, Helpdesk ve Keycloak testi `not_run` durumundadır.
Bağımsız kaynak incelemesinde açık hata kalmadı.
İnceleyici komut çalıştırmadı. İnceleyici 35 testin sonucunu kayıtlardan okudu.
Son güvenlik kapısının tekrarı bu incelemeye dahil değildir.

## Son dal kapıları

Bu kod önce eski depoda yazıldı. Kod 28 Kasım 2026 Cumartesi günü bu depoya taşındı (AJA-2370).
Taşımada karar numarası O-57 yerine O-63 oldu. O-57 başka bir karara verilmişti.
Komutlar yeni dalın çalışma klasöründe çalıştırıldı.

| Komut | Yerel sonuç |
| --- | --- |
| `~/.local/bin/python3.14 -B -m unittest discover -s apps/press_tr/tests -p test_operator_policy.py` | `pass`, 16 test |
| `~/.local/bin/python3.14 -B -m unittest discover -s apps/press_tr/tests -p test_financial_entry.py` | `pass`, 12 test |
| `~/.local/bin/python3.14 -B -m unittest discover -s apps/platform_core/platform_core/identity/tests -p test_staff_policy.py` | `pass`, 9 test |
| Ruff 0.14.10 `check` ve `format --check`, değişen 9 Python dosyası | `pass` |
| Semgrep 1.186.0 ve onay listesi | `pass`, yeni iki bulgu onaylı |
| Bandit, `dev/security/scans.py bandit` | `pass` |
| Sürüm artığı taraması, değişen 15 dosya | `pass` |
| `git diff --check` | `pass` |

Yeni testler önce kodsuz koşturuldu. 37 testin hepsi düştü. Düşen testler ayrı commit'tedir.

Ana daldaki bazı kapılar bu dalda da aynı sonucu verir. Bu sonuçlar bu işten gelmez:

- `dev/bin/module-boundaries` bir eski ihlal bulur. İhlal `identity/atonota/decision_api.py` dosyasındadır.
- `dev/tests` keşfi iki hata verir. Hatalar `test_e2e_stack` ve `test_release_residue` testlerindedir.
- Genel `apps/press_tr/tests` keşfi Frappe kurulu olmadığı için hata verir.

Frappe içindeki tam uygulama testi `not_run` durumundadır.
Gerçek HTTP, Helpdesk ve Keycloak testleri de `not_run` durumundadır.
Yerel başarı CI başarısı sayılmaz.

## Ek kurulum koşulları

Personel hesapları rol profili kullanmaz.
Rol profili, eski yetkiyi kayıt sırasında geri ekleyebilir.
Kod bu nedenle profil taşıyan hesabı reddeder.
Son görev rolü kalkınca sistem yönetilen rolleri temizler.
Destek kaydı da pasif olur.
Bu iptal, başarısız girişin geri almasına bırakılmaz.
Kod yalnız bu kimlik iptalini kalıcı yapar. Sonra girişi reddeder.

DevOps sorumlusu, `platform_staff_helpdesk_revision` ayarına sabitlenen Git kaydını yazar.
Değer 40 haneli küçük harfli onaltılık kayıt kodudur.
Bu ayar, Helpdesk sürümünün bağımsız doğrulama kanıtı değildir.
DevOps sorumlusu imaj kilidiyle çalışan kaydın aynı olduğunu ayrıca doğrular.
Helpdesk yoksa veya bu ayar eksikse personel girişi açılmaz.
DevOps sorumlusu, `PLT Ops Admin` rolünü ek izinsiz hazırlar.
DevOps sorumlusu, ERPNext satış ve muhasebe rollerinin kurulu olduğunu doğrular.
Operasyon sitesi eşlemesi aşağıdaki gibidir.

| Keycloak rolü | Operasyon sitesi rolü |
| --- | --- |
| `ops-admin` | `PLT Ops Admin` |
| `ops-billing` | `Sales User` |
| `ops-finance` | `Accounts Manager` |
| `ops-support` | `Agent` |

Helpdesk kaynak incelemesi [resmî HD Agent koduna](https://github.com/frappe/helpdesk/blob/main/helpdesk/helpdesk/doctype/hd_agent/hd_agent.py) dayanır.
Bu kaynak hareketli daldadır. Sabitlenen sürüm ayrıca doğrulanmalıdır.

Platform Core manifesti Frappe `>=16.56.0,<17.0.0` aralığını ister.
Platform Core manifesti Python `>=3.14,<3.15` aralığını ister.
Press TR manifesti Frappe `>=16.0.0,<17.0.0` aralığını ister.
Press TR manifesti Python `>=3.14` aralığını ister.
Yerelde okunan Frappe 16.50.0 yalnız Press için kanıttır.
Bu sürüm, Platform Core çalışma zamanı kanıtı sayılmaz.

Paperclip, belge düzeltmesini PO'ya alt görev olarak atamayı reddetti.
Yanıt `409 delegation_cycle` oldu.
PO, karar sitesindeki rol adını kendi akışında düzeltecektir.
Bu dal site dosyalarını değiştirmez.
