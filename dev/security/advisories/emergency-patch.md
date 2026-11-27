# Acil yama yönergesi

Bu yönerge G-142 ve K-26 kararına bağlıdır.
Acil yama, güvenlik açığını rutin yükseltmeyi beklemeden kapatan değişikliktir.

## Ne zaman başlar

Karar kaydında `decision` alanı `apply_now` ise bu yönerge başlar.
Acil yama rutin yükseltme takvimini beklemez.

## Hedef süreler

Hedef süreleri K-26 kararı belirler.
K-26 henüz ürün sahibinin onayını almadı.
Karar sitesinde bir başlangıç önerisi vardır.
Öneri onaylanana kadar taahhüt değildir.
Bu yönerge onaysız süre yazmaz.
Ürün sahibi K-26 kararını onaylarsa süreleri bu bölüme ekleyin.

## Adımlar

1. DevOps sorumlusu karar kaydını `records/` klasörüne yazar.
2. DevOps sorumlusu kaydı denetimden geçirir.
3. Platform ekibi yama için ayrı bir dal açar.
4. Platform ekibi düzeltilmiş sürümü ya da yamayı bu dala ekler.
5. Platform ekibi açığı gösteren bir test yazar. Test önce kırmızı olur.
6. Platform ekibi testleri ve güvenlik kapısını yerelde çalıştırır.
7. Ekip main dalına PR açar. PR açıklamasına karar kaydının adını yazar.
8. QA ve Committer PR'ı inceler.
9. DevOps sorumlusu yamayı test ortamında dener.
10. DevOps sorumlusu canlıya alma için ürün sahibinden onay alır.
11. DevOps sorumlusu yamayı canlıya alır ve sonucu doğrular.
12. DevOps sorumlusu karar kaydının gerekçesine sonucu ekler.

## Düzeltilmiş sürüm yoksa

Düzeltilmiş sürüm yoksa geçici önlem alın.
Örneğin etkilenen özelliği kapatın.
Geçici önlemi karar kaydının gerekçesine yazın.
Düzeltilmiş sürüm çıkınca 3. adımdan devam edin.

## Geri alma

Yama bir sorun çıkarırsa DevOps sorumlusu önceki sürüme döner.
Geri dönüş açığı yeniden açar.
Bu yüzden önce geçici önlemi uygulayın.
Sonra ürün sahibine haber verin.

## Sınırlar

- Ajanlar canlı sunucuya ve canlı veriye dokunmaz.
- Canlıya alma ve geri alma DevOps sorumlusunun işidir.
- Kayıtlara sır, token ve kişi verisi yazılmaz.
