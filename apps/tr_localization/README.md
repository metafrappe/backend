# Türkiye yerelleştirme uygulaması

`tr_localization`, ERPNext 16 için Türkiye kayıtlarını hazırlar.
Kod, deponun MIT lisansına bağlıdır. Bu karar proje kaydındaki D-2 kararından gelir.

Uygulama şu işleri yapar:

- Uygulama Türkiye hesap planındaki vergi hesaplarını doğrular.
- Uygulama yüzde 20, yüzde 10 ve yüzde 1 vergi şablonlarını ekler.
- Uygulama satış, alış ve ürün vergi şablonlarını ayrı oluşturur.
- Uygulama şablonları varsayılan yapmaz. Kullanıcı uygun şablonu seçer.
- Uygulama mevcut vergi şablonlarını değiştirmez.
- Farklı hesap planı kullanan şirketler bu kuruluma girmez.
- Uygulama Türk lirasının simgesini ve sayı biçimini ayarlar.
- Kullanıcı, yetkisi varsa TCMB kur aktarımını başlatır.

TCMB, Türkiye Cumhuriyet Merkez Bankasıdır.
Kur aktarımı bankanın `today.xml` dosyasını okur.
Uygulama bülten tarihini korur. Alış ve satış kurlarını ayrı kaydeder.
Uygulama tutarı bültendeki birim sayısına böler.
Kur kaydı, ERPNext'in dokuz ondalık basamak sınırına yuvarlanır.
Alış veya satış değeri boşsa uygulama o değeri üretmez.
İki değer de boşsa bülten reddedilir.
Örneğin 100 birim için gelen 35,50 değeri 0,355 olur.
Yedi günden eski bülten reddedilir. Gelecek tarihli bülten de reddedilir.
Uygulama zamanlanmış iş açmaz.
Günlük otomatik kur aktarımı bu görevin kapsamı dışındadır.
Sitede bulunmayan para birimleri atlanır. Diğer kurlar yazılır.
Yanıttaki `skipped_currencies` alanı atlanan para birimlerinin kodlarını gösterir.
`skipped_currency_count`, atlanan farklı para birimlerinin sayısını verir.
Alış ve satış kurları bu sayıda ayrı sayılmaz.
Kurulum yeni para birimi kaydı eklemez.

## Adres verisi

`TRL District`, il ve ilçe eşleşmelerini tutan kayıt türüdür.
Yönetici, doğrulanmış listeyi Frappe'nin veri aktarma ekranından yükler.
Her kayıt kaynak adresini ve doğrulama tarihini taşır.
Bu dal tam il ve ilçe listesini içermez.
Resmî kaynak erişimi doğrulanamadığı için örnek liste üretim verisi sayılmaz.
Liste hazır değilken Frappe'nin mevcut adres kuralları geçerlidir.
Yönetici tam listeyi doğrulayınca `trl_address_catalogue_ready` ayarını `true` yapar.
Bu ayar açılınca uygulama il ve ilçe eşleşmesini denetler.

Vergi ve kimlik numaraları yalnız uzunluk ve rakam biçimi bakımından denetlenir.
Bu denetim kimlik doğrulaması yapmaz.
Kimlik numarası isteğe bağlıdır. Alan, Address kaydının 1. izin düzeyini kullanır.
"Accounts Manager" ve "System Manager" rolleri bu alanı okur ve yazar.
"Sales User" rolü bu alanı göremez.
Frappe'nin "Administrator" hesabı yerleşik tam yetkisini korur.
Başka rolün 1. düzey okuma veya yazma izni varsa kurulum durur.
Kurulum mevcut izinleri silmez. Yönetici önce çakışmayı çözer.
Başka alan 1. izin düzeyini kullanıyorsa kurulum yine durur.
Vergi istisnasının kaynak adı "TRL Exempt" olur. Türkçe çevirisi "İstisna" olur.
Bu alanlara gerçek kişi verisiyle test yapılmaz.

## Kurulum

Yeni site kurulumu Press'in hazır yerelleştirme kaydını kullanır.
`erpnext` kaydına Türkiye için `tr_localization` bağlantısı eklenir.
Yeni site isteği `localisation_country=Türkiye` değerini taşımalıdır.
İlgili Release Group, uygulamayı aynı sürümde içermelidir.
Kiracı imajları uygulama kodunu ve Bench uygulama kaydını içerir.
Bench, Frappe uygulamalarını çalıştıran kurulumdur.
Mevcut siteler için sunucu devir adımları ayrıca uygulanır.
Migrate komutu alan izinlerini ve "Kuruş" yazımını mevcut kurulumlara uygular.
Migrate, kurulu uygulamanın veritabanı tanımını güncelleyen komuttur.
Sales Invoice e-belge alanları bu görevde hazırlanmaz. G-65 açık kalır.
G-41 kapsamındaki genel Türkçe ayarları bu uygulama sahiplenmez.

Yerel test komutu depo kökünde çalışır:

```bash
~/.local/bin/python3.14 -B -m unittest discover -s apps/tr_localization/tests
```

Gerçek Frappe testi yalnız ayrı test sitesinde çalışır:

```bash
bench --site test-tr-localization.localhost run-tests --app tr_localization
```

Test ve kapı komutları ortak kilidi gerektirir.
Sunucu adımları [devir notunda](../../docs/handoff/tr-localization.md) bulunur.
