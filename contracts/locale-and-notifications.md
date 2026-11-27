# Dil ve bildirim sözleşmesi

Bu belge A ve B takımının ortak sözleşmesidir. Kaynak iş AJA-1776, üst iş AJA-1733'tür.

Belge kuralları açıklar. Sözleşmenin kendisi şu dört dosyadır:

| Dosya | İçerik |
| --- | --- |
| `contracts/locales.json` | Açık diller, varsayılan dil, açık pazarlar ve bildirim dili sırası |
| `contracts/critical_messages.json` | Kritik iletilerin anahtarları ve kullanıldığı yerler |
| `contracts/terms_acceptance.schema.json` | Koşul kabul kaydı |
| `contracts/billing_identity.schema.json` | Fatura tarafı, adres şeması ve vergi numarası sonucu |

Sözleşme testi `contracts/tests/test_locale_contract.py` dosyasıdır.

## Kullanıcının amacı

Kullanıcı iletiyi kendi dilinde okur. Kullanıcı kabul ettiği koşulu sonra görebilir.

## 1. Açık diller

Açık dillerin listesi yalnız `contracts/locales.json` dosyasında durur. Şimdilik iki dil açıktır: `en` ve `tr`.

- Başka dosyalar listeyi kopyalamaz. Liste gerekirse bu dosyadan okunur.
- Yeni bir dili A Takımı PO ilan eder. Sonra bu dosyaya eklenir.
- Varsayılan dil `en-GB` olur (Karar 44).
- Açık pazar şimdilik yalnız `TR` pazarıdır.

Dil kodu iki küçük harftir. Örneğin `tr` bir dil kodudur. Bölge eki isteğe bağlıdır. Örneğin `en-GB` geçerli bir yazımdır.

## 2. Kritik iletiler

Kritik ileti, kullanıcıyı işinden alıkoyan iletidir. Örneğin giriş hatası, ödeme hatası ve hesap kilidi kritiktir.

`contracts/critical_messages.json` her ileti için üç bilgi taşır:

- `key` alanı dilden bağımsız ortak addır. Örneğin `auth.sign_in_failed` bir addır.
- `purpose` alanı iletinin ne zaman çıktığını yazar.
- `used_in` alanı iletinin kullanıldığı yerleri yazar.

Her yerin türü `surface` alanında yazar. Üç tür vardır:

| Tür | Yer | Anahtar |
| --- | --- | --- |
| `keycloak` | `identity/keycloak/themes/atonota/<tema>/messages/` | `message_key` alanı |
| `backend` | Frappe uygulamasının `translations/<dil>.csv` dosyası | `source` alanındaki İngilizce kaynak metin |
| `ui` | `atonota-web` deposundaki ileti dosyası | `message_key` alanı |

Frappe İngilizce kaynak metni anahtar olarak kullanır. Bu yüzden `en` dili için metin kodda aranır. Diğer diller için metin `translations/<dil>.csv` dosyasında aranır.

### Kim denetler

- Bu depodaki sözleşme testi `keycloak` ve `backend` yerlerini denetler. Test her açık dilde her anahtarı arar.
- `ui` yerlerini `atonota-web` deposunun testi denetler. O test aynı listeyi okur. Bu iş B Takımının AJA-1735 işindedir.
- Bir dilde kritik anahtar eksikse test düşer. Eksik anahtar sürüme giremez.

### Bilinen eksik

`billing.payment_failed` anahtarı bugün yalnız arayüzde kullanılacak. `atonota-web` bu anahtarı henüz taşımıyor. AJA-1735 testi bu yüzden önce kırmızı olur.

### Hesap kilidi

`auth.account_locked` iletisi `auth.sign_in_failed` iletisiyle aynı metni taşır. Bu bilinçli bir karardır. Böylece ileti hesabın var olup olmadığını söylemez.

## 3. Bildirim dili

Bildirimin dilini sistem seçer. Sıra `contracts/locales.json` dosyasındaki `notification_locale_order` alanındadır:

1. Önce alıcının kendi dili seçilir. Alanın adı `recipient` olur.
2. Alıcının dili boşsa kiracının dili seçilir. Alanın adı `tenant` olur.
3. İkisi de boşsa `en-GB` seçilir.

Bir değer yalnız dili açıksa sayılır. Örneğin alıcının dili `de` ise bu adım atlanır. Sonra kiracının dili denenir.

Bu kural e-postaya ve uygulama bildirimine uygulanır. Tarih ve sayı da seçilen dilin biçimiyle yazılır. Örneğin Türkçe kullanıcıya giden e-postada tarih Türkçe yazılır.

## 4. Koşul kabul kaydı

Kullanıcı bağlayıcı bir metni kabul edince sistem yeni bir kayıt yazar. Şema `contracts/terms_acceptance.schema.json` dosyasıdır.

Kayıt şu alanları taşır:

| Alan | Anlamı |
| --- | --- |
| `acceptance_id` | Kaydın tek kimliği |
| `terms_id` | Koşulun kimliği. Örneğin `terms-of-use` |
| `terms_version` | Ekranda gösterilen metnin sürümü |
| `shown_locale` | Ekranda gösterilen metnin dili |
| `user` | Kabul eden kullanıcının Keycloak kimliği (`sub`) |
| `accepted_at` | Kabul anı. UTC saatiyle ISO 8601 biçiminde yazılır |

- Kayıt yalnız eklenir. Ürün eski kaydı değiştirmez ve silmez.
- Yeni bir kabul yeni bir kayıttır.
- Kullanıcı kayıt sırasında dili değiştirebilir. Bu durumda `shown_locale` son gösterilen metnin dilidir.

## 5. Adres ve vergi numarası

Şema `contracts/billing_identity.schema.json` dosyasıdır.

### Adres şemasını ne belirler

Adres şemasını fatura ülkesi belirler. Alanın adı `billing_country` olur. Değer iki büyük harfli ülke kodudur.

Arayüz dili adres şemasını belirlemez. Örneğin İngilizce ekranı açan kullanıcı Türkiye adresi girebilir.

- Türkiye (`TR`) adresinde `line1`, `district` ve `province` zorunludur. `province` alanı ili tutar.
- Başka ülkeler şimdilik `default` biçimini kullanır. Bu biçimde il alanı yoktur.

### Ad ve unvan

Ad tek alandır. Alanın adı `name` olur. Tek parçalı ad geçerlidir. Soyadı alanı yoktur. Uzun şirket unvanı kesilmez.

### Vergi numarası sonucu

Vergi numarası denetiminin sonucu `result` alanındadır. Üç değer vardır:

| Değer | Anlamı | Ekran ne yapar |
| --- | --- | --- |
| `valid` | Servis numarayı doğruladı. | İşe devam eder. |
| `invalid` | Servis numarayı reddetti. | "Numara yanlış" der. |
| `unavailable` | Servis yanıt vermedi. Numara hakkında bilgi yok. | "Numara yanlış" demez. Taslağı korur. Sonra yeniden dener. |

Bu sonuç vergi tutarı değildir. Vergi tutarı `contracts/tax-result.md` sözleşmesindedir. O sözleşmenin kaynak işi AJA-1756'dır.

## Başarı, hata ve belirsiz sonuç

- Alıcının dili boşsa kiracının dili seçilir.
- Bir dilde kritik anahtar eksikse sözleşme testi düşer.
- Vergi servisi yanıt vermezse sonuç `unavailable` olur.

## Testi çalıştırma

```bash
python3 -I -m unittest discover -s contracts/tests -v
```
