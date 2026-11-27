# G-65 sunucu devri

Bu not AJA-104 görevine aittir. Dal adı `pc/tr-localization` olur.
Yerel birim testleri gerçek sunucu kurulumu kanıtı değildir.
G-65, aşağıdaki eksikler kapanmadan tamamlandı sayılmaz.

## Hazırlanan kod

G-42 kurulumu ERPNext'in hazır Türkiye hesap planını seçer.
Bu uygulama gereken vergi hesaplarını doğrular.
ERPNext hesapları oluşturduktan sonra uygulama vergi şablonlarını ekler.
Mevcut hesap planı ve vergi şablonları yeniden yazılmaz.
Kur aktarımı yetki denetiminden sonra çalışır.
Uygulama, kur dosyasının adresini kullanıcıdan almaz.
Adres, her zaman `https://www.tcmb.gov.tr/kurlar/today.xml` olur.

## Eksikler

- Resmî il ve ilçe listesinin tam kopyası yoktur.
- Gerçek test sitesinde kurulum henüz denenmedi.
- Gerçek HTTP isteğiyle yetki ve oturum denetimi henüz yapılmadı.
- Kiracı imajları bu dal için henüz derlenmedi.
- Press üzerinden yeni site açılması henüz denenmedi.
- Tam bir resmî TCMB bülteniyle deneme henüz yapılmadı.
- E-postası bulunmayan adreslerin kişisel veri silme yolu G-52 sahibini bekliyor.
- Sales Invoice özel e-belge alanları bu görevin kapsamı dışındadır.
- Tarayıcı denetimi bu görevin kapsamı dışındadır.

## Sunucu sırası

DevOps sorumlusu bu adımları yalnız ayrı test ortamında uygular.
Canlı ortama geçiş ayrıca yetki gerektirir.

1. DevOps sorumlusu bu dalın kiracı imajını derler.
2. DevOps sorumlusu ayrı bir test sitesi açar.
3. DevOps sorumlusu Press uygulama kayıtlarını oluşturur.

   Bu kayıtlar `erpnext` ve `tr_localization` adlarını taşır.
   DevOps sorumlusu Press sitesinde migrate komutunu çalıştırır.
   Kanca, Türkiye yerelleştirme bağlantısını `erpnext` kaydına ekler.
   Yeni site isteği `localisation_country=Türkiye` değerini taşımalıdır.
   Aynı sürümde etkin Release Group, uygulamayı içermelidir.
   Release Group, Press'in uygulama sürümlerini topladığı kayıttır.
   Press'in hazır yolu Site Plan'a bağlı kısıtlı grupları seçmez.

4. DevOps sorumlusu kurulu uygulamalarda `tr_localization` adını doğrular.
5. DevOps sorumlusu test şirketini Türkiye ülkesiyle oluşturur.
6. DevOps sorumlusu hesap planını ve üç vergi oranını doğrular.
7. DevOps sorumlusu resmî il ve ilçe listesini doğrular.
8. DevOps sorumlusu listeyi `TRL District` kayıtlarına aktarır.

   Liste tam doğrulanınca `trl_address_catalogue_ready` ayarı `true` yapılır.
   Bu ayar açılmadan il ve ilçe eşleşmesi denetlenmez.

9. DevOps sorumlusu uygulamanın gerçek Frappe testlerini çalıştırır.
10. DevOps sorumlusu kur aktarımını yetkili test kullanıcısıyla dener.
11. DevOps sorumlusu misafir ve yetkisiz kullanıcı isteklerini dener.
12. DevOps sorumlusu ikinci kur aktarımının kayıt çoğaltmadığını doğrular.

Kur aktarımı `POST /api/method/tr_localization.api.exchange.import_rates` adresini kullanır.
İstek bir oturumla yapılırsa CSRF belirteci gerekir.
CSRF belirteci, başka sitelerden izinsiz işlem başlatılmasını önleyen değerdir.
Yetkisiz istek kur dosyasını indirmemeli. Veritabanına kayıt da yazmamalı.

## Mevcut kurulumun güncellenmesi

DevOps sorumlusu önce ayrı test sitesinde migrate komutunu çalıştırır.
Migrate, uygulamanın veritabanı tanımını güncelleyen komuttur.
Bu komut kimlik alanı izinlerini ve "Kuruş" yazımını günceller.
Başka rolün 1. düzey okuma veya yazma izni varsa komut durur.
DevOps sorumlusu izin çakışmasını PO ile değerlendirir.
Komut mevcut rol izinlerini kendiliğinden silmez.
Başka alan 1. izin düzeyini kullanıyorsa kurulum yine durur.
Kaynak ve lisans seçilmeden adres listesi yüklenmez.
Liste tam doğrulanmadan `trl_address_catalogue_ready` ayarı açılmaz.
Günlük otomatik kur aktarımı kapsam dışıdır. Zamanlanmış iş kurulmaz.

## Kabul kanıtı

QA, aşağıdaki sonuçları kaydeder:

- Kurulu uygulama listesi `tr_localization` adını içerir.
- Yeni şirket Türkiye hesap planını kullanır.
- Alış, satış ve ürün şablonları üç vergi oranını içerir.
- İkinci şirket kaydı şablonları çoğaltmaz.
- Bilinen il ve ilçe eşleşmesi kabul edilir.
- Yanlış eşleşme reddedilir.
- Türk lirası `₺ 1.234,50` biçiminde görünür.
- Kur kaydının tarihi TCMB bülten tarihiyle aynıdır.
- Yetkisiz kullanıcı için yanıt kodu `403` olur.
- Aynı bülten ikinci kez işlendiğinde yeni kayıt oluşmaz.
- Bültende `AZN` ve `XDR` bulunup sitede yoksa diğer kurlar yazılır.
- Yanıt, atlanan kodları `skipped_currencies` alanında gösterir.
- Yanıt, farklı para birimi sayısını `skipped_currency_count` alanında gösterir.
- Kurulum yeni para birimi kaydı eklemez.
- "Accounts Manager" ve "System Manager" rolleri kimlik alanını okur ve yazar.
- "Sales User" rolü kimlik alanını göremez.
- Vergi istisnasının Türkçe çevirisi "İstisna" olur.
- Para birimi alt adı "Kuruş" olur.

## Geri alma

DevOps sorumlusu testten önce veritabanı yedeği alır.
Deneme başarısız olursa test sitesini bu yedekten geri getirir.
Hesap ve vergi kayıtları uygulama kaldırılarak silinmez.
Mevcut sitelerde farklı hesap planı varsa kurulum önce ayrı kopyada denenir.

## Kaynak kanıtı

Kaynak incelemesi yerel kurulumda yapıldı.
Gözlenen sürümler Frappe 16.56.0 ve ERPNext 16.55.0 oldu.
Python sürümü 3.14.10 oldu.
`requests` paketinin çalışan sürümü 2.33.1 oldu.
Uygulama bildirimi `requests~=2.33.0` aralığını kullanır.
Uygulama Frappe 16 ve ERPNext 16 kullanır.
ERPNext'in en düşük sürümü 16.55 olur.
Kiracı temel imajı `frappe/erpnext:v16.55.0` sürümüne sabitlidir.

Hazır hesap planı `erpnext/accounts/doctype/account/chart_of_accounts/verified/tr_chart_of_accounts.json` dosyasındadır.
Şirket sırası `erpnext/setup/doctype/company/company.py:426` satırında doğrulandı.
Yeni site yolu `press/api/site.py:287` satırında doğrulandı.
Frappe `after_insert` olayını hesaplar oluşmadan önce çağırır.
Bu yüzden vergi kancası `Company.on_update` olayını kullanır.
Kur kayıt adı `erpnext/setup/doctype/currency_exchange/currency_exchange.py:29` satırında doğrulandı.
Türkçe çeviri derlemesi `frappe/commands/utils.py:109` satırında doğrulandı.
İzin ekleme yolu `frappe/permissions.py:702` satırında doğrulandı.
Frappe, yüksek izin düzeyi için aynı rolün temel iznini ister.
Bu denetim `frappe/core/doctype/doctype/doctype.py:1907` satırındadır.
Alan okuma ve yazma süzmesi `frappe/model/meta.py:745` satırında doğrulandı.
İki kiracı imajı da `tr_localization` çevirilerini derleme listesine alır.

Gerçek okurla denenmedi.
