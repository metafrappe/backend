# G-121 yetki matrisi: veri yüzeyleri ve testleri

Bu belge 28 Kasım 2026 Cumartesi günü yazıldı. Belgeyi AJA-2280 işi yazdı.

Belge G-121 maddesinin tek matrisidir. Her satır bir veri yüzeyini gösterir. Her satırda Frappe yolu ve test dosyası vardır.

## Kısa sonuç

- Erişim kuralı her veri yüzeyinde aynı sonucu verir.
- Yetkisi olmayan kullanıcı başkasının kaydını hiçbir yüzeyde görmez.
- Bu iş beş eksik yüzeye ret testi ekledi.
- Testler iki açık buldu. İki açık da kapatıldı.

## Terimler

- Yüzey, kaydın kullanıcıya ulaştığı yoldur. Örneğin liste, PDF ve arama birer yüzeydir.
- Kurallı kayıt türü, en az bir etkin erişim kuralı olan kayıt türüdür.
- Daraltılmış kullanıcı, kuralı bütün kayıtları göstermeyen kullanıcıdır.
- Ret testi, yetkisiz isteğin reddedildiğini gösteren testtir.

## Testler nerede?

Test dosyaları `apps/platform_core/platform_core/access/` klasöründedir. Aşağıdaki yollar bu klasöre göredir.

Testler isteği Frappe'nin WSGI uygulamasından geçirir. Kayıtlar ve kişiler uydurmadır. Ortak test sınıfı `tests/base.py` dosyasındadır.

## Matris

Frappe satır numaraları Frappe 16.56.0 sürümüne aittir.

| Yüzey | Frappe yolu | Kural nasıl girer | Test dosyası |
| --- | --- | --- | --- |
| REST listesi | `frappe.get_list` (`__init__.py:1378`) | Liste kancası | `tests/test_record_rule.py`, `tests/test_surfaces.py` |
| REST tek kayıt | `check_permission("read")` (`api/v2.py:68`) | Kayıt kancası | `tests/test_record_rule.py`, `tests/test_surfaces.py` |
| REST güncelleme | `check_permission("write")` ve `save` (`api/v2.py:200`) | Kayıt kancası | `tests/test_hierarchy.py`, `tests/test_review.py` |
| Alan düzeyi | `permlevel` | Frappe alanı çıkarır | `tests/test_field_level.py` |
| Liste raporu | `desk/reportview.py:19` | Liste kancası | `tests/test_surfaces.py` |
| Liste dışa aktarması | `desk/reportview.py:540` | Liste kancası | `tests/test_surfaces.py` |
| Bağlantı araması | `desk/search.py:263` | Liste kancası | `tests/test_surfaces.py`, `test_link_search.py` |
| Bağlantı araması, özel işlevle | `desk/search.py:133` | Kurallı türde reddedilir | `test_link_search.py` |
| Paylaşma | `share.py:143` | Kayıt kancası | `tests/test_sharing.py` |
| Sorgu ve betik raporu | `desk/query_report.py:968` | Rapor kapısı | `test_reports.py`, `tests/test_report_rules.py` |
| Hazır rapor dosyası | `core/doctype/file/file.py:976` | Kurallı veride kapalı | `tests/test_report_rules.py` |
| Zamanlanmış e-posta raporu | `Auto Email Report` | Kurallı veride kapalı | `tests/test_auto_email_report.py` |
| Yapay zekâ araçları | `platform_core.access.ai_tools` | Kayıt ve liste kancası | `tests/test_ai_tools.py` |
| **Dosya ve ekler** | Dosya kaydı (`file.py:1088`), dosya listesi (`file.py:1128`), özel dosya indirme (`utils/response.py:294`) | Kayıt kancası ve liste kancası. Ek, bağlı olduğu kaydın kuralına uyar. | `tests/test_file_surface.py` |
| **Arka plan işleri** | İş kuyruğu (`utils/background_jobs.py:179`), işçi (`background_jobs.py:251`) | İş, kuyruğa koyan kullanıcı adına çalışır. Kancalar işte de çalışır. | `tests/test_background_job_surface.py` |
| **Realtime olayları** | Oda denetimi (`realtime/__init__.py:126`), `list_update` olayı (`model/document.py:1784`) | Kayıt odası kayıt kancasını sorar. Kurallı türün liste odası daraltılmış kullanıcıya kapalıdır. | `test_realtime.py` |
| **Global arama** | `utils/global_search.py:480` | Her sonuç kayıt kancasından geçer (`global_search.py:538`). | `tests/test_global_search_surface.py` |
| **PDF indirme** | Tek PDF (`utils/print_format.py:389`), çoklu PDF (`print_format.py:68`), yazdırma sayfası ve HTML (`www/printview.py:413`) | Yazdırma izni kayıt kancasını sorar (`printview.py:544`). | `tests/test_pdf_surface.py` |

Kalın satırlar bu işte eklendi.

## Yeni testler ne gösterir?

### Dosya ve ekler

- Gizli bir kaydın özel eki açılmaz. Dosya kaydı da indirme adresi de 403 döner.
- Kullanıcı kendi kaydının ekini açar ve indirir.
- Gizli bir kaydın açık dosya kaydı da 403 döner.
- Dosya listesinde yalnız görünen kayıtların ekleri vardır.
- Bütün kayıtları gören kullanıcı bütün ekleri görür. Bu, testin kontrol durumudur.

### Arka plan işleri

- Çoklu PDF işi kuyruğa kullanıcının adıyla girer.
- İşçi işi bu kullanıcı adına çalıştırır. Gizli kayıt için iş izin hatası verir. PDF dosyası oluşmaz.
- İş içindeki liste yalnız kullanıcının kayıtlarını döner.
- İş içinde gizli kayda erişim izin hatası verir.

### Realtime olayları

- Misafir hiçbir odaya giremez.
- Kullanıcı gizli bir kaydın odasına giremez.
- Kullanıcı kendi kaydının odasına girer.
- Daraltılmış kullanıcı kurallı türün liste odasına giremez.
- Bütün kayıtları gören kullanıcı liste odasına girer.
- Kuralsız türün liste odası değişmez.

### Global arama

- Arama sonucunda gizli kayıt yoktur.
- Tek kayıt türünde arama da gizli kaydı döndürmez.
- Kuralı olmayan kullanıcı hiçbir kayıt bulmaz.
- Bütün kayıtları gören kullanıcı bütün kayıtları bulur. Bu, testin kontrol durumudur.

### PDF indirme

- Tek PDF, çoklu PDF ve kayıt türü haritalı çoklu PDF 403 döner.
- Yazdırma HTML'i ve yazdırma sayfası 403 döner.
- Yanıtta gizli kaydın başlığı yoktur.

## Testlerin bulduğu açıklar

### Dosya listesi gizli kayıtların eklerini gösteriyordu

Frappe dosya listesinde yalnız kayıt türünü okuma iznini sorar (`file.py:1128`). Bu yüzden daraltılmış kullanıcı bütün kayıtların eklerini listeliyordu. Liste dosya adını ve bağlı kaydın adını gösteriyordu.

Açık dosya kaydı da herkese açıktı. Kayıt, bağlı olduğu gizli kaydın adını gösteriyordu.

Düzeltme şudur:

1. Motor dosya listesine bir koşul ekler. Kurallı kaydın eki yalnız kayıt görünüyorsa listelenir.
2. Motor dosya kaydının okuma kararını da daraltır. Kurallı kaydın eki yalnız kaydın okuyucusuna açılır.

Kod `access/engine.py` ve `access/hooks.py` dosyalarındadır.

### Liste odası gizli kayıtların adlarını yayıyordu

Frappe bir kayıt değişince liste odasına `list_update` olayı gönderir. Olay kaydın adını ve değiştiren kullanıcının adresini taşır. Liste odasına kayıt türünü okuyabilen herkes giriyordu.

Düzeltme şudur:

1. Motor Frappe'nin oda denetim ucunun yerine kendi işlevini koyar.
2. Kurallı türün liste odası yalnız bütün kayıtları gören kullanıcıya açılır.
3. Kayıt odası Frappe'nin denetimini korur.

Kod `access/realtime.py` dosyasındadır. Ucun sözleşmesi `contracts/platform_core-access.openapi.yaml` dosyasındadır.

Bu düzeltmenin bir bedeli vardır. Daraltılmış kullanıcının listesi kendiliğinden yenilenmez. Kullanıcı listeyi elle yeniler.

## Kalan sınırlar

- Açık dosyanın içeriğini web sunucusu izin sormadan verir. Kurallı kayıtların ekleri özel dosya olmalıdır.
- Özel dosyanın sahibi, kaydı göremese bile dosyayı indirebilir. Frappe sahibe her zaman izin verir (`file.py:1097`).
- Sistem kodu `frappe.get_all` ve ham SQL ile kancayı atlar. Bu bir kullanıcı yüzeyi değildir. Karar notunun 9. bölümü bu durumu anlatır.
- Testler gerçek bir realtime sunucusu ve gerçek bir işçi açmaz. Testler bu iki sürecin web sürecine sorduğu yolu sınar.

## Doğrulama

Bu iş için yerelde şu komutlar koştu:

- `dev/bin/test platform_core --module <modül>` ile beş yeni test dosyası,
- aynı yolla erişim motorunun bütün eski test dosyaları,
- `uvx ruff@0.14.10 check` ve `format --check`,
- `dev/bin/ai-readiness`, `dev/check_boundaries.py` ve ad kapısı.

`tests/test_performance.py` dosyası yalnız ölçüm sitesinde koşar. Bu işte koşmadı.
