# Hazırlık sunucusunda uçtan uca sınama

Bu not bütün yığının hazırlık sunucusunda birlikte sınanmasını anlatır. Not 23 Kasım 2026 Pazartesi günü yazıldı. Not 28 Kasım 2026 Cumartesi günü bu depoya taşındı. Bilgiler aynı gün `main` dalıyla karşılaştırıldı.

## Kapsam

- Bu not denetim raporunun 5. bölümündeki 19. işi kapsar.
- Bu iş [proje kaydındaki](../../PROJECT-RECORD.md) bir teknik borcu kapatır. Borç şudur: identity-sync canlı Keycloak, Press ve kiracı ile denenmedi.
- Bu not G-151 gereksiniminin sınama kanıtını da verir. G-151 her yükseltme için rc ortamında uçtan uca kanıt ister.

Hazırlık sunucusu, üretimden önce yığını denediğimiz sunucudur. Ortamlar belgesi dört ortam tanımlar: alpha, beta, rc ve prod. Bu not hazırlık sınaması için rc ortamını önerir. Ortam seçimini Hüseyin Cengiz onaylar.

## Görev sahibi

- Görev sahibi Hüseyin Cengiz'dir.
- integration-e2e işi testleri sunucuya uyarlar.
- DNS kayıtlarını Asistan Hüseyin uygular.

## Adımlar

1. Hüseyin Cengiz Hetzner'de hazırlık sunucusunu kurar. Bu, denetim raporundaki 14. iştir.
2. Hüseyin Cengiz DNS kayıtlarının türünü, adını ve değerini yazar. Örneğin `id.atonota.net` kaydı bu listededir.
3. Asistan Hüseyin bu kayıtları GoDaddy'de uygular.
4. Hüseyin Cengiz kayıtların sunucuya ulaştığını doğrular.
5. Hüseyin Cengiz TLS sertifikasını alır.
6. Hüseyin Cengiz Keycloak, Press, bir kiracı ve identity-sync servisini kurar.
7. integration-e2e işi testlerin hedef adresini ayara bağlar.
8. integration-e2e işi testleri yalnız örnek hesaplarla çalıştırır. Hesap adresleri `example.test` ile biter.
9. integration-e2e işi giriş, çıkış, kullanıcı eşitleme ve Press girişi akışlarını dener.
10. integration-e2e işi sonucu ve komutları bir kanıt dosyasına yazar.
11. Hüseyin Cengiz bu borcun kapanış kararını proje kaydına yazdırır.

## Bilinen engel

Bugünkü testler yalnız yerel yığında çalışır. Bunu iki dosya gösterir:

- `e2e/local.ts` adresi her zaman `http://<ad>.localhost:<port>` biçiminde kurar.
- `e2e/README.md` inceleme hesabı komutunun yerel olmayan adreste durduğunu yazar.

Bu yüzden 7. adım ayrı bir geliştirme işidir. İş, Team B PO ajanına açılmalıdır. İş yerel korumayı kaldırmaz. Sunucu hedefi ayrı ve açık bir ayarla seçilir.

## Bağımlılıklar

- Hazırlık sunucusu kurulmuş olmalı. Bu, 14. iştir.
- DNS kayıtları uygulanmış ve doğrulanmış olmalı. Bunlar 15., 16. ve 17. işlerdir.
- Press sunucu kurma akışı hazırlıkta denenmiş olmalı. Bu, 18. iştir.
- Sunucuya gerçek kişi verisi girecekse veri güvencesi kapanmış olmalı. Ayrıntı [data-assurance-gate.md](data-assurance-gate.md) dosyasındadır.

## Doğrulama

1. Yerel kapı önce geçmeli. integration-e2e işi depo kökünde `e2e/stack up` ile yerel yığını açar.
2. Hazırlık koşusunda her akış `pass` ya da `fail` sonucuyla yazılır.
3. Koşulmayan akış `not_run` diye yazılır.
4. Hüseyin Cengiz sağlık denetimini çalıştırır: `deploy/bin/health rc <paket klasörü>`.

## Kabul ölçütü

- Keycloak, Press, kiracı ve identity-sync hazırlık sunucusunda birlikte sınandı.
- Giriş, çıkış, kullanıcı eşitleme ve Press girişi geçti.
- Kanıt dosyasında komutlar, tarih ve sonuçlar var.
- Kanıt dosyasında parola ve token yok.
- Borç proje kaydının teknik borç tablosundan çıktı.
