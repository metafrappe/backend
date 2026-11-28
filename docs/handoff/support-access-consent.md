# Müşteri onaylı destek erişimi

Bu belge AJA-101 dilimini ve AJA-176 düzeltmesini anlatır.
Son güncelleme 24 Kasım 2026 Salı günü yapıldı.
Gereksinim kimliği G-18 olur.
Dal `pc/support-access-consent` adını taşır.
Kararlar O-63 ve O-64 olur.

## Yerel kapsam

Sistem mevcut Press `Support Access` kaydını kullanır.
Destek çalışanı gerekçeli bir talep açar.
Müşteri takımının sahibi talebi ayrıca onaylar.
Sistem sahibin kimliğini `Team.user` alanından okur.

Onay, çalışanı ve destek takımını bağlar.
Onay, siteyi ve gerekçeyi de bağlar.
Sistem sonradan kapsam değişikliğini reddeder.
Müşteri yeni kapsam için yeni talebi onaylar.

Normal onay 3, 6, 12 veya 24 saat sürer.
Yönetici onayı ayrı talepte verilir.
Bu talep tek siteyi kapsar ve 3 saat sürer.
Bu talep başka izin içermez.

İlk destek işlemi yalnız site adını ve durumunu okur.
Sistem her okumada süreyi ve onayı yeniden denetler.
Süre bittiğinde sistem sonraki okumayı reddeder.
Sistem gerekçeyi aynı işlemde yorum kaydına yazar.
Yorum yazılamazsa sistem veriyi döndürmez.

Destek rolü taşıyan hesaplar eski Press erişim yollarını kullanamaz.
Sistem kullanıcısı türü bu kısıtı kaldırmaz.
Bu sınır, takımda olmayan platform çalışanının site girişini de kapatır.

Müşteri takımının sahibi ve üyeleri kendi sitelerine girebilir.
Sistem üyeliği sitenin takımından okur.
Üyelik, `Team Member` kaydında bulunmalıdır.
Üst takım üyeliği tek başına alt takımın sitesini açmaz.
Ürün sorumlusu bu ek kapsamı ayrı değerlendirebilir.

Destek hesabı `/account-deletion` sayfasından CSRF değeri alır.
CSRF, tarayıcıdan gelen sahte isteklere karşı koruma değeridir.
Yalnız `GET` ve `HEAD` sayfa isteklerine izin verilir.
Sayfa önbelleğe alınmaz.
Destek hesabı `/app` gibi diğer sayfalarda 403 alır.
Destek hesabı hesap silme ucunu kullanamaz.

`Administrator` hesabı yalnız sunucunun iş bağlamında site oturumu alabilir.
Frappe, iş bağlamını `execute_job` içinde `frappe.local.job` alanında oluşturur.
Sistem ayrıca `frappe.local.request` alanının boş olmasını ister.
HTTP isteği varsa iş kaydı izin sağlamaz.
İş kaydı yoksa yönetici girişi reddedilir.
HTTP girdisi bu iki sunucu alanını oluşturamaz.
Sunucu kabuğundaki yetkili kod bu uygulama sınırının dışındadır.
Örneğin kabuktaki `frappe.enqueue(now=True)` çağrısı iş bağlamını oluşturabilir.
Bu değişiklik yeni zamanlanmış iş kurmaz.

## Kapanmayan işler

G-18 bütünü henüz kapanmadı.
Yönetici onayı kaydediliyor ancak yönetici oturumu açılmıyor.
Destek çalışanının eski oturum üretme yolları bu nedenle kapalıdır.
Destek çalışanının takım kimliğine geçiş yolu da kapalıdır.
Müşteri sahibinin ve doğrudan takım üyelerinin giriş yolları korunur.

Kiracı oturumunun onaya bağlanması henüz uygulanmadı.
Süre ve iptal bildiriminin kiracıda denetlenmesi de henüz uygulanmadı.
AJA-177 bu iki eksiği O-65 kararıyla kapattı.
Ayrıntı [kiracı destek oturumu notundadır](support-tenant-session.md).
Bu eksikler yalnız sunucu ayarı değildir.
Platform ekibi bu kodu ve testlerini hazırlamalıdır.

Gerçek Press kaydı ve HTTP istekleri ayrı yerel ortamda denendi.
Arayüz eklenmedi.
Müşterinin onay ekranı bu dalın tesliminde yoktur.
Yeni uçlar O-55 kararı gereği özel ağda kalır.

## Bağlantılar ve kayıt alanları

Uç sözleşmesi `backend/contracts/press_tr-support.openapi.yaml` dosyasındadır.
Uçlar yalnız `POST` isteği kabul eder.
Tarayıcı oturumu, Frappe'nin sahte istek korumasını kullanır.
Bu koruma isteğin oturum sahibinden gelmesini denetler.

| Uç | İşlem |
| --- | --- |
| `press_tr.api.support.request_access` | Destek çalışanı tek site için talep açar. |
| `press_tr.api.support.approve_access` | Müşteri sahibi talebi ve süreyi onaylar. |
| `press_tr.api.support.revoke_access` | Müşteri sahibi onayı geri alır. |
| `press_tr.api.support.site_status` | Destek çalışanı izinli sitenin durumunu okur. |

Yeni alanlar müşterinin onaylayan hesabını ve onay saatini tutar.
Üçüncü alan, onay kuralının sürümünü tutar.
Sistem bu alanları kendisi doldurur.
Eski onaylar bu alanlara sahip değildir.
Sistem eski onayları yeni okuma yolunda reddeder.

Onay ve okuma kayıtları mevcut `Comment` türünde tutulur.
Kayıtlar kullanıcı kimliği, site, gerekçe, kapsam ve süre içerir.
Bu veriler kişisel veri içerebilir.
Kayıtlar herkese açık depoya aktarılmaz.
Saklama ve silme politikası ilgili müşteri sözleşmesine bağlanmalıdır.
Bu dal yeni bir saklama süresi belirlemez.

## Sürüm kanıtı

Manifest Python için `>=3.14` koşulunu taşır.
Manifest Frappe için `>=16.0.0,<17.0.0` koşulunu taşır.
Yerel birim testleri Python 3.14.10 ile çalıştı.
HTTP test ortamında Python 3.14.8 gözlendi.
HTTP test ortamında Frappe 16.50.0 gözlendi.
Yerel Press kaynak kodu `7a4384d5eec9f0f0dce4124e9dd48b106e51222f` kaydındadır.
Kaynaklar mevcut yerel kurulumlardan yalnız okunarak alındı.
HTTP testleri yeni `fs-aja176` ortamında çalıştı.
Bu ortam yalnız uydurma hesap ve site kayıtları kullandı.
Çalışan 7400 yığını değiştirilmedi veya yeniden başlatılmadı.
Yeni dalın bağımlılık kilidi yeniden çözülmedi.

Press'in `has_support_access` işlevi sistem kullanıcısına doğrudan izin veriyor.
İşlevin sorgusu talep sahibini süzmüyor.
Bu nedenle yeni yol eski izin işlevini kullanmıyor.
Yeni yol destek rolünün eski ağ uçlarına erişimini kapatıyor.

Frappe 16 sınıf genişletme kancası kullanılıyor.
Resmi Press ve Frappe kaynakları değiştirilmedi.
`Support Access` kayıt kancası doğrudan kayıt yollarını da denetler.
SQL, veritabanına doğrudan komut verme yoludur.
Doğrudan SQL veya ele geçirilmiş sunucu bu uygulama sınırının dışındadır.

## Önce test kanıtı

AJA-176 düzeltmesinde ilk kilitli koşu üç hatayı gösterdi.
Sayfa erişimi, takım üyeliği ve sistem işi testleri izin hatasıyla düştü.
Düzeltmeden sonra 33 birim testi geçti.
Eski kodla yapılan HTTP testi de aynı sayfa hatasını gösterdi.
Rollü destek hesabı `/account-deletion` sayfasında 403 aldı.
Bu sonuç gerçek tarayıcı çereziyle yapılan HTTP isteğidir.
Görsel tarayıcı denemesi değildir.

Aşağıdaki kayıtlar önceki AJA-101 çalışmasına aittir.

İlk koşu eksik destek modülü nedeniyle durdu.
Bu sonuç davranış hatası kanıtı sayılmadı.
Sonraki test, yönetici talebindeki iki açığı gösterdi.
Birden çok site ve ek izin kabul ediliyordu.
İki denetim `ConsentDenied not raised` sonucu verdi.
Ardından kod bu birleşimleri reddedecek biçimde düzeltildi.

Bu ikinci koşu sırasında kapı kilidi AJA-72 görevindeydi.
Yanlışlıkla 13 test çalıştırıldı.
Bu koşu ortak kilit kuralını ihlal etti.
Sonraki kapılarda sahiplik komut içinde denetlenecek.

## AJA-176 doğrulama kaydı

Kontroller ortak kapı kilidiyle sırayla çalıştırıldı.
Bu görevin testlerinde kilit sahipliği her komuttan önce denetlendi.
Sekiz eski HTTP testi korundu.
Yedi yeni HTTP testi gerçek destek rolünü kullandı.
İki ek test gerçek Press giriş işlevlerini çağırdı.
Kiracıya giden dış bağlantılar bu iki testte taklit edildi.

HTTP paketi toplam 17 testi geçti.
Paket aşağıdaki durumları doğruladı:

1. Rollü destek hesabı tarayıcı çereziyle CSRF değeri aldı.
2. Onaysız okuma 403 döndü.
3. Onaylı okuma 200 döndü.
4. Süresi biten onay 403 döndü.
5. Geri alınan onay 403 döndü.
6. Başka çalışan ve başka takım 403 aldı.
7. Site başka takıma geçince eski onay 403 döndü.
8. İki başarılı okuma tam iki erişim yorumu oluşturdu.
9. `/app`, `/dashboard` ve sayfanın alt yolu 403 döndü.
10. Müşteri üyesinin dört eski giriş yolu çalıştı.
11. `sync_setup_wizard_status` işi site kurulum durumunu güncelledi.

Dört giriş yolu şunlardır:

- `Site.login_as_admin`
- `Site.login_as_team`
- `Site User.login_to_site`
- `Product Trial Request.get_login_sid`

Görevdeki “Site User.login” adı kaynakta `login_to_site` olarak geçer.
Birim testleri insan isteğindeki `Administrator` hesabını ayrıca reddetti.
Birim testleri destek rolü olan takım üyesini de reddetti.
Bağımsız inceleme bu ret için gerçek Press testi de önerdi.
Bu olumsuz senaryo aynı giriş testine eklendi.

İlk dal kontrolünde üç sorun bulundu.
Testlerde `_` adı çeviri işlevi için ayrılmıştı.
Bu geçici değişkenlere açıklayıcı adlar verildi.
Eski devir notundaki kişi adları yayımlama kontrolüne takıldı.
Bu adlar görev kapsamından çıkarıldı.
Değişen kaynak, mevcut güvenlik incelemesinin özetini de değiştirdi.

Güvenlik aracı mevcut 19 Press istisnasını yeniden incelemeye açtı.
Yeni istisna veya kural atlama eklenmedi.
Gerekçeler değişiklik farkıyla yeniden değerlendirildi.
Bandit aracındaki mevcut örnek parola istisnasının özeti de yenilendi.
Örnek parola değişmedi. Yeni istisna eklenmedi.
Bağımsız mimar AJA-202 görevinde tasarım engeli bulmadı.
İnceleme salt okunur yapıldı.
Bu inceleme otomatik test veya üretim onayı değildir.

Son dal kapıları geçti.
Yayımlama testi, commit öncesinde Git'e hazırlanmış dosyaları denetledi.
Bu seçim için `RELEASE_REV=:` kullanıldı.
Kontrol Git kayıtlarını okur. Çalışma klasöründeki değişikliği kendiliğinden okumaz.

| Komut | Yerel sonuç |
| --- | --- |
| `backend/dev/bin/module-boundaries` | `pass` |
| `UV_OFFLINE=1 backend/dev/bin/security-audit` | `pass` |
| `backend/dev/bin/ai-readiness` | `pass` |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/tests` | `pass`. 103 test çalıştı. İki test atlandı. |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/naming/tests` | 68 test geçti. |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/apps/press_tr/tests -p 'test_support_*.py'` | 33 test geçti. |
| `SupportAccessTests` sınıfından seçilen `IdentityHttpTest` testleri | Ek ret senaryosuyla birlikte 17 test geçti. |

Ruff 0.14.10 ile kod ve biçim denetimi yapıldı.
Ruff, Python kodundaki biçim ve bazı hata kurallarını denetler.
Yerel deneme ayarı e-posta gönderimini kapatır.
Mevcut test çalıştırıcısı bu ayarı iş sonunda geri yükler.

Frappe çekirdek çeviri ve manifest denetimleri `not_run` durumundadır.
Kapı için gereken 16.56.0 çekirdek dosyaları yerelde sağlanmadı.
Bu iki alt denetim geçmiş sayılmadı.
Gerçek tarayıcı, eşzamanlı işlem ve CI doğrulaması `not_run` durumundadır.
CI, sunucudaki otomatik kontrol koşusudur.
Playwright kapsam dışıdır ve çalıştırılmadı.

## Testi yeniden çalıştırma

QA ayrı bir yerel Press ortamı kullanmalıdır.
QA önce ortak kapı kilidini almalıdır.
Kurulum adımları `backend/apps/press_tr/README.md` dosyasındadır.
Tam test komutu şu biçimdedir:

```sh
PRESS_TEST_COMPOSE_PROJECT=<yerel-proje> PRESS_TEST_PANEL_URL=<panel-adresi> \
  FS_COLIMA_PROFILE=default sh backend/apps/press_tr/tests/run.sh
```

Yalnız destek paketi için mevcut HTTP sunucusunda aşağıdaki seçim kullanılır.
Komut Bench ortamında, `sites` klasöründe çalıştırılır.
`PYTHONPATH`, `press_tr/tests` klasörünü içermelidir.
`PANE_PORT`, HTTP sunucusu portundan üç küçük olmalıdır.

```python
import unittest
from press_tr.api.test_support import SupportAccessTests
from test_identity_http import IdentityHttpTest

names = unittest.defaultTestLoader.getTestCaseNames(SupportAccessTests)
suite = unittest.TestSuite(IdentityHttpTest(name) for name in names)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
```

QA iş sonunda yalnız kendi test sunucusunu durdurmalıdır.
QA kendi kilidini de kaldırmalıdır.
Bu belge canlı sunucuyu değiştirme yetkisi vermez.
Bu belge dağıtım veya genel ağ erişimi onayı vermez.

## Yazım denetimi

Komutlar ve alan adları teknik okur için aynen korundu.
Gerçek okurla denenmedi.
