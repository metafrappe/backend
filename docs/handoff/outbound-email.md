# G-17 ve G-47 sunucu devri

Bu not gerçek e-posta sunucusunun kurulumunu anlatır.
Yerel test, gerçek teslimat kanıtı sayılmaz.
Bu görev canlı sunucuda değişiklik yapmaz.

## İki kurulum adımı

1. Hüseyin Cengiz e-posta sunucusunu hazırlar.
   Hüseyin Cengiz her kaydın türünü, adını ve değerini yazar.
   Kayıtlar SPF, DKIM, DMARC ve PTR doğrulamasını kapsar.
   Bu kayıtlar gönderen sunucuyu ve alan adını doğrular.
   Sunucu bağlantısı 587 portunda STARTTLS kullanır.
   STARTTLS, bağlantıyı şifrelemeyi zorunlu kılan gönderim yöntemidir.
   Sunucunun sertifikası geçerli olmalıdır.
   Şifreler güvenli ayar alanında tutulur.
   Şifreler bu nota veya Git'e yazılmaz.

2. Asistan Hüseyin hazırlanan kayıtları GoDaddy'de girer.
   GoDaddy dışındaki PTR kaydını Hüseyin Cengiz uygular.
   Hüseyin Cengiz kayıtların sonucunu doğrular.
   Hüseyin Cengiz deneme mesajının alıcıya ulaştığını doğrular.
   Doğrulama bitmeden gönderim açılmaz.

## Kabul için gereken kanıt

- Gönderen alanının SPF, DKIM ve DMARC denetimleri geçer.
- PTR kaydı, gönderici sunucunun adresiyle eşleşir.
- Geçersiz sertifikayla bağlantı reddedilir.
- Şifresiz gönderim reddedilir.
- Onaysız göndericiyle gönderim reddedilir.
- Kiracı kendi alanıyla deneme mesajı gönderir.
- Kota dolunca sonraki gönderim reddedilir.
- Yedi e-posta türü doğru Türkçe metni gösterir.
- Fatura tutarı, site adı ve davet bağlantısı korunur.

Hüseyin Cengiz kanıt dosyasına yalnız gizli olmayan sonuçları yazar.
Gerçek alan adı ayarları bu depoya eklenmez.
Alıcı adresleri ve mesaj içerikleri kanıt dosyasına eklenmez.

## Mevcut durum

Sunucu kurulumu ve gerçek DNS denetimi `not_run` durumundadır.
DNS, alan adlarının kayıt sistemidir.
Gerçek e-posta teslimatı `not_run` durumundadır.
Yerel uygulama ve test çalışması sürüyor.

Gerçek okurla denenmedi.
