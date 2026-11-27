# Dil ve sayfalama testlerinin devri

AJA-97, G-73 ve G-150 için sunucu testlerini ve liste ucunu taşır.
Panel işi kapsam dışı: atonota-web.

## Yapılanlar

1. Liste ucu `platform_core.api.collection.list_records` adını taşır.
2. Uç bir sayfada en çok 20 satır döndürür. Karar O-73'tür.
3. Alt tablo yalnız tek üst kaydın içinde okunur.
4. Sabit metin denetimi `dev/check_translations.py` dosyasındadır.
5. Denetimin testi `dev/tests/test_translation_guard.py` dosyasındadır. Bu test 4. dal kapısında koşar.
6. Yerel sorgu planı henüz alınmadı. Plan `docs/explain-collection-local.md` dosyasına yazılacak.

## Sabit metin denetimi

Denetim `frappe.throw` ve `frappe.msgprint` çağrılarına bakar.
İletinin `_()` içinden geçmesi gerekir.
Düz, biçimli veya birleştirilmiş metin satır numarasıyla raporlanır.
Test ve yama dosyaları taranmaz. Bu dosyalar kullanıcıya metin göstermez.

Denetimi tek başına şu komut koşar:

```bash
~/.local/bin/python3.14 -B dev/check_translations.py
```

## Güvenlik incelemesi gerekir

Okuyucu kullanıcı Website User türündedir.
Bu yüzden yeni uç `hooks.py` içindeki `website_user_allowed_methods` listesine eklendi.
Bu değişiklik `platform_core` Semgrep onay özetini geçersiz kılar.
Özeti yalnız bağımsız güvenlik incelemesi yeniler.
Team B PO bu incelemeyi ayrı bir görevle açmalıdır.

## Alt tablo alan izni

Frappe liste yolu, üst kayıttaki tablo alanının izin düzeyini denetlemez.
Yeni uç bu alanı kendisi denetler. Riskin geri kalanını AJA-183 görevi izler.

## Kapı kilidi gelince yapılacaklar

Kod commit'lendi. Şu adımlar kapı kilidini bekliyor:

1. Ucu eklemeden önceki commit'te sayfalama testini koşun. Test düşmelidir.
2. Son commit'te dilin, sayfalamanın ve özetin testlerini koşun.
3. Aynı yerel veritabanında sorgu planını alın.
4. Planı `docs/explain-collection-local.md` dosyasına yazın.
5. Altı dal kapısını sırayla koşun.
