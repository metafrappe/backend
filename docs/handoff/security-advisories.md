# Güvenlik açıkları ve destek süreleri

Bu not güvenlik açıklarının takibini ve bileşen yükseltmelerini anlatır. Not 23 Kasım 2026 Pazartesi günü yazıldı. Not 28 Kasım 2026 Cumartesi günü bu depoya taşındı. Bilgiler aynı gün `main` dalıyla karşılaştırıldı.

## Kapsam

- Gereksinimler G-142 ve G-151'dir.
- Bu not denetim raporunun 5. bölümündeki 21. işe girdi verir. Yayın onayı bu kayıtlara bakar.
- CI güvenlik kapısı bu notta değildir. O iş [ci-security.md](ci-security.md) dosyasındadır.

Güvenlik danışmanlığı, bir yazılımın açığını duyuran resmî nottur. Örneğin GitHub güvenlik notları birer danışmanlıktır.

## Görev sahibi

- Görev sahibi Hüseyin Cengiz'dir.
- Platform ekibi açığın bizi etkileyip etkilemediğini değerlendirir.
- Yama süreleri bir insan kararıdır. Karar sahibi proje sahibidir. Bu karar K-26'dır.

## Adımlar

1. Hüseyin Cengiz izlenen bileşenlerin listesini yazar.
2. Listede Frappe, ERPNext, HRMS, Press, Agent, CRM, Helpdesk, Keycloak ve Hocuspocus bulunur. Arayüz bağımlılıkları da bulunur.
3. Hüseyin Cengiz her bileşen için kaynakları yazar. Kaynaklar GitHub danışmanlıkları, NVD ve satıcı sürüm notlarıdır.
4. Yeni bir danışmanlık gelince Platform ekibi kurulu sürümü yazar.
5. Platform ekibi etkilenen sürüm aralığını yazar.
6. Platform ekibi ilgili özelliğin bizde açık olup olmadığını yazar.
7. Platform ekibi saldırının ön koşulunu yazar.
8. Platform ekibi düzeltilmiş sürümü yazar.
9. Hüseyin Cengiz kararı kayda geçirir. Karar üç seçenekten biridir: hemen uygula, planla ya da uygulanamaz.
10. Karar "uygulanamaz" ise Platform ekibi sürüm ve ayar kanıtını kayda ekler.
11. Acil yama normal yükseltme takvimini beklemez. Hüseyin Cengiz yamayı önce rc ortamında dener.
12. Hüseyin Cengiz her ay destek durumu kaydı yazar.
13. Aylık kayıtta her bileşenin destek bitiş tarihi bulunur. Örneğin ERPNext 16 için plan 2029 sonudur.
14. Hüseyin Cengiz Node ve Python sürümlerinin destek sonunu da yazar.
15. Hüseyin Cengiz her rutin yükseltmeyi rc ortamında dener.
16. Hüseyin Cengiz yükseltmenin uçtan uca sınama sonucunu kayda ekler.

Destek durumu son sürümün tarihinden çıkarılmaz. Resmî destek tablosu okunur.

Bu not zamanlanmış iş kurmaz. Aylık kaydı bir kişi elle yazar.

## Bağımlılıklar

- Proje sahibi K-26 yama sürelerini onaylamalı. Onaydan önce süreler söz değildir.
- Başlangıç önerisinde saldırıda kullanılan ya da kritik açık 72 saat içinde kapanır.
- Başlangıç önerisinde yüksek açık 7 gün içinde kapanır.
- rc ortamı kurulmuş olmalı.
- Uçtan uca sınama rc ortamında çalışmalı. Ayrıntı [staging-e2e.md](staging-e2e.md) dosyasındadır.
- CI güvenlik kapısı kurulmuş olmalı. Ayrıntı [ci-security.md](ci-security.md) dosyasındadır.

## Doğrulama

1. Son tarama raporunu depo kökünde şu komut üretir: `dev/bin/release-report`.
2. Hüseyin Cengiz raporda yüksek ya da kritik açık arar.
3. Her yüksek ya da kritik açığın kayıtta bir kararı olmalıdır.
4. Aylık destek kaydı bu ayın tarihini taşımalıdır.

## Kabul ölçütü

- Her yüksek ya da kritik açığın karar kaydı var.
- "Uygulanamaz" kararında sürüm ve ayar kanıtı var.
- Acil yama normal takvimi beklemedi.
- Aylık destek kaydı var.
- Her yükseltmenin rc ortamında uçtan uca kanıtı var.
- K-26 yama süreleri proje sahibinin onayıyla kayıtta.
