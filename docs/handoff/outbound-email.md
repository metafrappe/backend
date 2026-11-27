# G-17 ve G-47 devir notu

Bu not Türkçe e-posta ve giden e-posta işinin açık kalan sunucu adımlarını anlatır. Kod ve testler bu daldadır. Karar gerekçesi proje kaydındaki O-69 kararıdır.

Yerel test gerçek teslimat kanıtı değildir. Bu iş canlı sunucuda değişiklik yapmadı.

## Kodda hazır olanlar

- Press TR uygulaması yedi e-posta türü için Türkçe şablon taşır. Şablonlar `apps/press_tr/press_tr/templates/emails/` klasöründedir.
- Altı şablon Press şablonuyla aynı adı taşır. Frappe önce `press_tr` dosyasını okur. Press kodu değişmez.
- Fatura e-postası yeni bir şablondur. Adı `ptr_invoice` olur. Press v0.154.1 kendi fatura e-postasını göndermez.
- Press konu satırlarını çeviri işlevi olmadan yazar. `localize_subject` kancası bilinen konuları Türkçe konuyla değiştirir.
- `send_queued` kancası her alıcıdan önce gönderim kurallarını denetler. Kurallar şunlardır:
  - Operatör gönderimi açmış olmalıdır.
  - Gönderen adres ve sunucu onaylı olmalıdır.
  - Onayda SPF, DKIM, DMARC ve PTR denetimi geçmiş olmalıdır.
  - Bağlantı 587 portunda STARTTLS kullanmalıdır.
  - Sunucunun sertifikası doğrulanmalıdır.
  - Günlük kota dolmamış olmalıdır.

STARTTLS, bağlantıyı şifreleyen gönderim yöntemidir. SPF, DKIM ve DMARC, gönderenin alan adına ait olduğunu gösteren DNS kayıtlarıdır. DNS, alan adlarının kayıt sistemidir. PTR, sunucu adresini sunucu adına bağlayan kayıttır.

## Site ayarı

Gönderim kuralı Press sitesinin `site_config.json` dosyasından okunur. Anahtarın adı `outbound_email_policy` olur. Ayar yoksa hiçbir e-posta gönderilmez.

Ayarın biçimi aşağıdadır. Değerler örnektir.

```json
{
  "outbound_email_policy": {
    "enabled": true,
    "verified_senders": [
      {
        "email": "notice@tenant.example.test",
        "smtp_server": "relay.example.test",
        "spf": true,
        "dkim": true,
        "dmarc": true,
        "ptr": true
      }
    ],
    "quota": {"feature": "outbound_email_daily", "plan": "example-plan", "limit": 500}
  }
}
```

Bu ayarı depoya yazmayın. Gerçek alan adı ve sunucu adı yalnız sunucudaki ayar dosyasına girer.

Kiracı kendi gönderici adresini Frappe'nin “Email Account” kaydıyla tanımlar. Operatör DNS denetimini görmeden adresi `verified_senders` listesine eklemez.

## Üç kurulum adımı

1. Hüseyin Cengiz e-posta sunucusunu hazırlar.
   - Hüseyin Cengiz her DNS kaydının türünü, adını ve değerini yazar.
   - Kayıtlar SPF, DKIM, DMARC ve PTR kayıtlarıdır.
   - Sunucu 587 portunda STARTTLS kullanır.
   - Sunucunun sertifikası geçerli olmalıdır.
   - Şifreler sunucudaki güvenli ayar alanında kalır. Şifreler bu nota ve Git'e yazılmaz.

2. Asistan Hüseyin hazırlanan kayıtları GoDaddy'de girer.
   - Asistan Hüseyin kayıtları Hüseyin Cengiz'in yazdığı türde, adda ve değerde girer.
   - PTR kaydı GoDaddy'de değildir. PTR kaydını Hüseyin Cengiz sunucu sağlayıcısında girer.

3. Hüseyin Cengiz sonucu doğrular.
   - Hüseyin Cengiz dört DNS denetiminin geçtiğini görür.
   - Sonra `outbound_email_policy` ayarını Press sitesine yazar.
   - Sonra bir deneme e-postası gönderir.
   - Doğrulama bitmeden `enabled` değeri `true` yapılmaz.

## Kabul için gereken kanıt

Hüseyin Cengiz şu sonuçları kanıt dosyasına yazar:

- Gönderen alanının SPF, DKIM ve DMARC denetimleri geçer.
- PTR kaydı gönderen sunucunun adresiyle eşleşir.
- Geçersiz sertifikayla bağlantı reddedilir.
- Şifresiz gönderim reddedilir.
- Onaysız göndericiyle gönderim reddedilir.
- Kiracı kendi adresiyle deneme mesajı gönderir.
- Kota dolunca sonraki gönderim reddedilir.
- Yedi e-posta türü Türkçe konu ve metinle gelir.

Kanıt dosyasına yalnız gizli olmayan sonuçlar girer. Alıcı adresleri ve mesaj içerikleri kanıt dosyasına girmez.

## Açık maddeler

1. Kota sınırı şimdilik site ayarından okunur. Plan özelliğinden siteye yazan yol henüz yok. Bu yol fiyat işiyle birlikte yapılır.
2. Kiracı sitelerinin kendi gönderimi bu işte bağlanmadı. Bu işte yalnız Press sitesinin e-postaları denetlenir. Kurallar Frappe kullanmayan bir modülde durur. Kiracı tarafı aynı modülü ortak kitaplığa taşıyarak kullanabilir.
3. Fatura e-postasını tetikleyen Press olayı bu işte bağlanmadı. Şablon ve `prepare` işlevi hazırdır.
4. Press sürümü değişince konu listesi yeniden denetlenir. Liste `outbound_email/messages.py` dosyasındaki `PRESS_SUBJECTS` listesidir.
5. Press TR test paketi Press kapsayıcısında bu dalda koşulmadı.

## Mevcut durum

Sunucu kurulumu `not_run` durumundadır. Gerçek DNS denetimi `not_run` durumundadır. Gerçek e-posta teslimatı `not_run` durumundadır.
