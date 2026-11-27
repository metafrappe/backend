# Fiyat ve vergi sonucu sözleşmesi

Bu belge A ve B takımının ortak sözleşmesidir. Kaynak iş AJA-1756, üst iş AJA-1731'dir.

Sözleşmenin kendisi `contracts/tax_result.schema.json` dosyasıdır. Bu belge kuralları açıklar.

Ekran, fatura belgesi ve muhasebe kaydı aynı alanları kullanır. Böylece üç yer aynı tutarı gösterir.

## Kullanıcının amacı

Kullanıcı vergili ve vergisiz tutarı ayırt eder. Kullanıcı verginin neden hesaplanmadığını da görür.

## Vergiyi ne belirler

Vergiyi fatura ülkesi belirler. Alanın adı `billing_country` olur. Değer iki büyük harfli ülke kodudur.

Arayüz dili vergiyi belirlemez. Bu yüzden sözleşmede dil alanı yoktur. Örneğin Türkçe ekranı açan bir kullanıcı başka ülkeye fatura kesebilir.

## İşlem türü ve iş anahtarı

Alanın adı `operation` olur. Üç değer vardır:

| Değer | Anlamı | İş anahtarı |
| --- | --- | --- |
| `quote` | Fiyat hesabıdır. Yalnız okur. | Gerekmez. Alan `null` olur. |
| `purchase` | Satın almadır. | Gerekir. |
| `refund` | İadedir. | Gerekir. |

İş anahtarının kuralları `contracts/idempotency.md` belgesindedir. O belgenin kaynak işi AJA-1749'dur.

## Tutar biçimi

Her tutar iki alan taşır: `value` ve `currency`.

- `value` ondalık metindir. Ayraç noktadır. Örneğin `"112.34"` bir değerdir.
- `value` hiçbir zaman kayan noktalı sayı olmaz. Kayan noktalı sayı kuruşu kaydırabilir.
- `currency` üç büyük harfli para birimi kodudur. Örneğin `EUR` bir koddur.
- Ekrandaki yazımı istemci seçer. Örneğin istemci `112,34 €` gösterebilir.

Oran da ondalık metindir. Oran yüzde olarak yazılır. Örneğin `"12.34"` yüzde 12,34 demektir.

Bu belgedeki ve şemadaki oranlar kurgusaldır. Ülke kodu da kurgusaldır: `ZZ`. Gerçek oran yazmayın.

## Yuvarlama

Şemadaki `x-rounding` alanı bu kuralı makine için yazar.

### Basamak sayısı

Her tutar tam iki ondalık basamak taşır. Örneğin `"10.00"` doğrudur. `"10"` ve `"10.0"` yanlıştır.

Şema bunu `value` alanının deseniyle denetler. Oran bu kurala girmez. Oran en çok dört ondalık basamak taşır.

### Yöntem

Sunucu vergiyi yarımda çifte yuvarlar. Bu yöntemin adı `ROUND_HALF_EVEN` olur. Türkçe adı "banker yuvarlaması"dır.

Yöntem tam yarımda sonucu çift kuruşa götürür. Örnekler şunlardır:

- `1.025` değeri `1.02` olur.
- `1.035` değeri `1.04` olur.
- `1.026` değeri `1.03` olur.

### Yuvarlama yeri

Sunucu vergiyi satırda yuvarlar. Satırın vergisi şöyle bulunur:

1. Sunucu `net` tutarını `tax_rate` oranıyla çarpar.
2. Sunucu sonucu 100'e böler.
3. Sunucu sonucu iki ondalık basamağa yuvarlar.

Sunucu toplamları yeniden yuvarlamaz. Toplam vergi, yuvarlanmış satır vergilerinin toplamıdır. Böylece ekran, fatura ve muhasebe aynı kuruşu gösterir.

Şemadaki son örnek bu kuralı gösterir. Örnekte üç satır var. Her satırın net tutarı `10.25`, oranı `10.00` olur.

- Her satırın ham vergisi `1.025` olur. Satır vergisi `1.02` olur.
- Toplam vergi `3.06` olur.
- Ham vergiler toplanıp yuvarlansaydı sonuç `3.08` olurdu. Sözleşme bunu yasaklar.

### Kaynak

- Basamak sayısının kaynağı G-41 gereksinimidir. G-41 `currency_precision=2` değerini ister.
- Yöntemin kaynağı K-8 kararıdır. K-8 `rounding_method` için "Banker's Rounding" önerir.
- K-8 açık bir karardır. Bu yüzden yöntem için PO onayı istendi.
- Satırda yuvarlama bu sözleşmenin kararıdır. "Toplamlar" bölümü zaten toplamı satırların toplamı sayar.

## Satır alanları

Her satır şu alanları taşır:

- `net`: satırın vergisiz tutarı.
- `tax_rate`: satırın oranı. Oran yoksa `null` olur.
- `tax`: satırın vergisi.
- `gross`: satırın vergili tutarı. `net` ile `tax` toplamına eşittir.
- `tax_status`: vergi durumu.
- `reason_code`: durumun nedeni.
- `label_key_short`: 320 piksel ekran için kısa durum metninin anahtarı.
- `label_key_long`: geniş ekran ve belge için uzun metnin anahtarı.

Metin anahtarı dilden bağımsızdır. Metni istemci kendi çeviri dosyasından alır.

## Vergi durumları

Her durum ayrı bir değerdir. Her durumun kendi neden kodları vardır. Bir neden kodu yalnız bir durumda kullanılır.

| Durum | Anlamı | Vergi tutarı | Neden kodları |
| --- | --- | --- | --- |
| `calculated` | Vergi hesaplandı. | Sıfırdan büyük | `TAX_STANDARD_RATE`, `TAX_REDUCED_RATE` |
| `zero_rated` | Sıfır oran uygulandı. | `"0.00"` | `TAX_ZERO_RATE_EXPORT`, `TAX_ZERO_RATE_GOODS` |
| `exempt` | Satır vergiden istisnadır. | `"0.00"` | `TAX_EXEMPT_BY_LAW`, `TAX_EXEMPT_CUSTOMER` |
| `reverse_charge` | Vergiyi alıcı beyan eder. | `"0.00"` | `TAX_REVERSE_CHARGE_B2B` |
| `not_calculated` | Vergi hesaplanmadı. | `null` | `TAX_MISSING_BILLING_COUNTRY`, `TAX_UNSUPPORTED_COUNTRY`, `TAX_MISSING_TAX_ID` |
| `service_unavailable` | Vergi servisi kapalı. | `null` | `TAX_SERVICE_UNAVAILABLE`, `TAX_SERVICE_TIMEOUT` |

## Bilinmeyen vergi sıfır değildir

Vergi servisi kapalı olabilir. Bu durumda vergi bilinmez. Sunucu `tax` alanını `null` yazar. Sunucu `gross` ve `tax_rate` alanlarını da `null` yazar.

Sunucu bu durumda `"0.00"` yazmaz. `"0.00"` vergi bilindi ve sıfır çıktı demektir. Bu yanlış bilgi olur.

Aynı kural `not_calculated` durumu için de geçerlidir.

İstemci boş vergiyi sıfır gibi göstermez. İstemci durum metnini gösterir. Örneğin "Vergi hesaplanamadı" yazar.

## Toplamlar

`totals` alanı üç tutar taşır: `net`, `tax` ve `gross`.

- `net` her zaman satırların toplamıdır.
- Bir satırın vergisi `null` olabilir. Bu durumda toplam `tax` ve toplam `gross` da `null` olur.
- Bütün satırların vergisi biliniyorsa toplamlar satırların toplamıdır.

## Fatura kopyası

Satın alma ve iade bir fatura üretir. Sunucu fatura kesilince sonucun kopyasını `invoice` alanına yazar.

Kopya şu alanları taşır: fatura numarası, faturanın özgün tarihi, para birimi, satırlar ve toplamlar. Her satır kendi oranını taşır.

Kopya salt okunurdur. Oran sonra değişebilir. Sunucu yine de kopyayı değiştirmez. Belge ve muhasebe kaydı her zaman bu kopyayı okur.

Vergisi bilinmeyen satır faturaya giremez. Bu yüzden `not_calculated` ya da `service_unavailable` satırı olan sonuçta fatura kesilmez.

Fiyat hesabında (`quote`) `invoice` alanı `null` olur.

## Sonuçlar

Fiyat hesabının üç ayrı sonucu vardır:

1. Vergi hesaplandı. Satırlar `calculated`, `zero_rated`, `exempt` ya da `reverse_charge` durumundadır.
2. Servis kapalı. En az bir satır `service_unavailable` durumundadır.
3. Vergi hesaplanmadı. En az bir satır `not_calculated` durumundadır.

İstemci üç sonucu ayrı metinle gösterir.

## Denetim

Sözleşmeyi `contracts/tests/test_tax_result_contract.py` testi denetler. Test yalnız Python standart kitaplığını kullanır.

Testi çalıştırmak için şu komutu kullanın:

```bash
python3 -I -m unittest discover -s contracts/tests -v
```
