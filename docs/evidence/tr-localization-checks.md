# G-65 yerel kontrol kaydı

## Ana dala taşıma, 28 Kasım 2026 Cumartesi

Bu iş AJA-2434 kaydıdır. Eski dal `pc/tr-localization` bu depoya taşındı.
Yeni dalın adı `pc/aja2411-tr-localization` olur.
Dosyalar `backend/` öneki olmadan taşındı.
Aşağıdaki eski bölümler eski dalın kaydıdır. Eski komut yolları bu yüzden `backend/` ile başlar.

Ana dalda G-41 Türkiye ayarları vardır. Kod `apps/platform_core/platform_core/config/turkey_setup.py` dosyasındadır.
G-41 kodu TRY para birimini etkin yapar. Bu yüzden `configure_currency` artık bu alanı yazmaz.
Bu kuralı yeni bir test denetler. Test adı `test_currency_configuration_leaves_enabling_to_g41` olur.

Ana dalda Press uygulamasının `after_migrate` listesi zaten vardı.
Eski dal ikinci bir `after_migrate` satırı ekliyordu. Bu satır eski listeyi silerdi.
Kayıt kancası bu yüzden mevcut listeye eklendi.
Bu durumu `test_press_after_migrate_keeps_existing_hooks_and_adds_registration` testi denetler.

Güvenlik kilidi ve Semgrep özeti bu taşımada değişmedi.
Bu iki araç hâlâ `backend/` önekli yolları arar. Önek bu depoda yoktur.
Araçların düzeltilmesi ayrı bir iştir.

| Komut | Sonuç |
| --- | --- |
| `python3.14 -B -m unittest discover -s apps/tr_localization/tests`, kod taşınmadan önce | `fail`. 45 test koştu. 1 başarısızlık ve 56 hata oldu. |
| Aynı komut, kod taşındıktan sonra | `pass`. 45 test geçti. |
| `uvx --offline ruff@0.14.10 check` ve `format --check` | `pass`. 21 dosya denetlendi. |
| `python3.14 -B -m unittest discover -s dev/naming/tests` | `pass`. 68 test geçti. |
| `dev/bin/module-boundaries` | Yeni modüllerde ihlal yok. Ana daldaki `decision_api.py` sözdizimi bulgusu sürüyor. |
| `RELEASE_REV=: python3.14 -B -m unittest discover -s dev/tests` | 140 test koştu. 2 hata çıktı. İki hata da `backend/` önekini bekleyen eski testlerden gelir. |

Gerçek Frappe testleri bu taşımada da `not_run` durumundadır.
Kiracı imajı yerelde derlenmedi.


Çalışma dalı `pc/tr-localization` olur. Görev numarası AJA-104 olur.
Bu kayıt yalnız yerel çalışmayı anlatır. G-65 henüz kapanmadı.

## Önce başarısız olan testler

Beklenen vergi oranları G-65 kaydından alındı.
Hesap numaraları ERPNext'in hazır Türkiye hesap planından alındı.
Kur basamak sınırı gerçek `Currency Exchange` alanından alındı.

Şu davranışlar koddan önce başarısız testle gösterildi:

- Vergi şablonlarının eksik olması.
- Adres eşleşmesinin ve numara biçiminin denetlenmemesi.
- Türk lirası biçiminin kurulmaması.
- Kur bülteninin aktarılmaması.
- Press yerelleştirme ilişkisinin eklenmemesi.
- Kur değerinin yerel dokuz basamak sınırını aşması.

Bağımsız inceleme sonrasında ek testler de önce başarısız oldu.
Bu testler boş adres listesini ve farklı hesap planlarını kapsadı.
Değiştirilebilir ilçe anahtarları ve birleşik kur kayıtları da sınandı.
İlk teslimin yerel koşusunda 32 test geçti.
Bu testler Frappe veritabanının yerine kontrollü test nesneleri kullanır.
Gerçek Frappe testleri ayrıca hazırlandı. Bu testler henüz çalıştırılmadı.

## QA sonrasında eklenen testler

AJA-199 incelemesi ilk teslimi reddetti. A Takımı PO düzeltme kapsamını belirledi.
Yeni testler, eski kod üzerinde beş başarısızlık ve üç hata verdi.
Eksik para birimi, rol izinleri, migrate kancası ve çeviri bu kapsamdaydı.
"Kuruş" yazımı da aynı koşuda başarısız oldu.
İlk koşu, içe aktarılan test sınıfını iki kez saymıştı.
Test sınıfının doğrudan içe aktarımı kaldırıldı. Tekrarlanan test sayımı düzeltildi.
Düzeltmeden sonraki yerel koşuda 43 farklı test geçti.

Kur testi, USD, AZN ve XDR içeren kontrollü bir bülten kullandı.
Test sitesi yalnız USD para birimini var saydı.
USD alış ve satış kurları yazıldı. AZN ve XDR atlandı.
Yanıt iki farklı para birimini kodlarıyla bildirdi.
Bütün para birimleri eksik olduğunda da kayıt yazılmadı.
Kurulum testleri yalnız mevcut TRY kaydının güncellendiğini gösterdi.

İzin testleri iki yetkili rolün okuma ve yazma hakkını sınadı.
"Sales User" rolünün 1. düzey hakkı olmadığını da sınadı.
Mevcut başka rol izniyle çakışma, alan oluşturulmadan reddedildi.
Sahibe özel mevcut izin satırı korundu. Tekrarlanan kurulum satır çoğaltmadı.
Bağımsız inceleme, başka alanın aynı izin düzeyini kullanmasını da denetlememi istedi.
Yeni test önce başarısız oldu. Kurulum bu çakışmayı da reddedecek şekilde düzeltildi.
Gerçek Frappe alan süzme testi ayrıca eklendi. Bu test henüz çalıştırılmadı.

## Dört kod bozmasının sonucu

Her bozma ayrı uygulama kopyasında uygulandı. Asıl dal değiştirilmedi.
Her deneme ilgili testi `python3.14 -B -m unittest` komutuyla çalıştırdı.
Her denemenin çıkış kodu `1` oldu. Testler dört bozmayı da yakaladı.

| Bilerek yapılan bozma | Başarısız olan test |
| --- | --- |
| Yüzde 20 ve yüzde 10 hesapları yer değiştirdi. | `test_taxes_install_all_rates_on_company_scoped_accounts` |
| Kimlik numarası uzunluğu 11 yerine 10 oldu. | `test_identity_number_requires_exactly_eleven_ascii_digits` |
| `frappe.only_for` rol denetimi silindi. | `test_import_denies_wrong_role_before_network_even_with_create_permission` |
| Bülten yaşı sınırı 7 yerine 30 gün oldu. | `test_exchange_accepts_seven_days_but_rejects_eight_days` |

Vergi testi yüzde 20, yüzde 10 ve yüzde 1 eşlemelerini ayrı denetler.
Satış, alış ve ürün vergi şablonlarının hesapları birlikte sınanır.
Kimlik testi 10 ve 12 haneyi reddeder. Test 11 haneyi kabul eder.
Bülten testi 7 günlük veriyi kabul eder. Test 8 günlük veriyi reddeder.

## Komutlar ve sonuçlar

Komutlar depo kökünde çalıştırıldı. Ortak kilit kullanıldı.
Kapılar ve testler aynı anda çalıştırılmadı.

| Komut | Sonuç |
| --- | --- |
| `backend/dev/bin/module-boundaries` | `pass`. İhlal bulunmadı. |
| `UV_OFFLINE=1 backend/dev/bin/security-audit` | `pass`. Yeni güvenlik ihlali bulunmadı. |
| `backend/dev/bin/ai-readiness` | `pass`. İki çekirdek kaynak denetimi `not_run` kaldı. |
| `RELEASE_REV=: ~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/tests` | `pass`. 103 test koştu. İki test atlandı. |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/naming/tests` | `pass`. 68 test geçti. |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/apps/tr_localization/tests` | `pass`. 43 test geçti. |
| `uvx --offline ruff@0.14.10 check backend/apps/tr_localization` | `pass`. |
| `uvx --offline ruff@0.14.10 format --check backend/apps/tr_localization` | `pass`. 19 dosya denetlendi. |
| Türkçe denetim betiği | README, devir notu, proje kaydı ve kontrol kaydında hata bulunmadı. |

AI kapısı yerel Frappe çeviri kataloğunu bulamadı.
Aynı kapı yerel Frappe paket bildirimini de bulamadı.
Bu iki alt denetim başarılı sayılmadı.
Çalışan Frappe kaynağı ayrıca salt okunur olarak incelendi.

İlk geliştirme testi koşusu, önceki commit içindeki kişi adları nedeniyle başarısız oldu.
Çalışma dosyası düzeltilince aynı kontrol önceki commit'i okumayı sürdürdü.
Bu test varsayılan olarak Git'teki son commit'i denetler.
`RELEASE_REV=:` seçeneği, commit için hazırlanmış içeriği denetler.
Hazırlanmış içerikte 101 test geçti. İki test atlandı.
Herkese açık devir notunda rol adı kullanıldı. Görev sahibi özel görev yorumunda belirtildi.

## Güvenlik incelemesi

Press kancası değişince 19 eski Semgrep onayı geçersizleşti.
Semgrep, kodda riskli kalıpları arayan araçtır.
Bağımsız inceleyici 19 gerekçeyi kaynaklarıyla yeniden denetledi.
Yeni kayıt kancası kimlik ve yetki yollarını değiştirmiyor.
İnceleme sonucunda yalnız aynı kapsamın kaynak özeti yenilendi.
Yeni istisna eklenmedi. Kurallar ve gerekçeler değiştirilmedi.

QA düzeltmeleri ayrıca bağımsız `standards-reviewer` incelemesinden geçti.
İnceleyici başka alanın 1. izin düzeyini paylaşması riskini buldu.
Bu bulgu önce başarısız testle gösterildi. Ardından kod düzeltildi.
Son salt okunur incelemede açık kod bulgusu kalmadı.
İnceleyici komut veya test çalıştırmadı. Kontrolleri geliştirici çalıştırdı.
Bu inceleme A Takımı QA'nın kabul kararının yerine geçmez.

## Çalışan sürümler

- Yerel Python sürümü 3.14.10 oldu.
- Yerel Frappe sürümü 16.56.0 oldu.
- Yerel ERPNext sürümü 16.55.0 oldu.
- Yerel `requests` sürümü 2.33.1 oldu.
- Uygulama bildirimi `requests~=2.33.0` aralığını kullanır.
- Kiracı imajı sürümü ve özeti mevcut Dockerfile kayıtlarından korundu.

## Açık kabul ölçütleri

Resmî adres kaynağı ve lisans koşulu henüz seçilmedi.
Tam il ve ilçe verisi henüz yüklenmedi.
O-58 kararına göre günlük otomatik kur aktarımı kapsam dışıdır.
Hazırlanan kur ucu yalnız yetkili kullanıcının POST isteğiyle başlatılır.
Sales Invoice özel e-belge alanları bu görevin kapsamı dışındadır.
Bu alanlar ve adres verisi tamamlanmadan G-65 kapanmaz.

Şu denemeler `not_run` durumundadır:

- Gerçek Frappe kurulum ve kayıt testleri.
- Gerçek HTTP ile izin, oturum ve yöntem denetimleri.
- Kiracı imajlarının derlenmesi.
- Press üzerinden yeni site açılması.
- Tam resmî TCMB bülteninin işlenmesi.
- Kişisel veri silme akışının gerçek kayıtlarla denenmesi.
- Sürekli bütünleştirme sistemi, yani CI kontrolleri.

Playwright bu görevin kapsamı dışındadır. Bu kontrol `not_applicable` durumundadır.
Sunucu adımları [devir notunda](../handoff/tr-localization.md) bulunur.
Bu eksikler kapanmadan G-65 tamamlandı sayılmaz.

## Yazım denetimi

Yeni metindeki uzunluk uyarıları açıklama cümlelerine aittir.
Bu cümleler 15 kelime sınırını aşmaz.
Proje kaydının eski bölümlerinde uzunluk uyarıları sürüyor.
Bu uyarılar değiştirilmeyen alıntılara ve eski açıklamalara aittir.
O-58 kararında uzunluk uyarısı bulunmadı.
Kod, komut ve dosya yolları teknik biçimiyle korundu.
Gerçek okurla denenmedi.
