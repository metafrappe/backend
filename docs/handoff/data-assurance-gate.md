# Veri güvencesi kapısı

Bu not gerçek kişi verisinin Hetzner'e girmesinden önceki kapıyı anlatır. Not 23 Kasım 2026 Pazartesi günü yazıldı. Not 28 Kasım 2026 Cumartesi günü bu depoya taşındı. Bilgiler aynı gün `main` dalıyla karşılaştırıldı.

## Kapsam

- Bu not denetim raporunun 5. bölümündeki 13. işi kapsar.
- Kaynak, frappesetup sitesinin karar listesindeki Karar 27'dir. Bu liste bu depoda yoktur.
- [Proje kaydı](../../PROJECT-RECORD.md) da aynı sınırı yazar: "Türkiye'deki kişilerin verisi güvence kurulmadan Hetzner'e konmaz."
- Bu not hukuki görüş değildir. Son metni bir avukat onaylar.

## Görev sahibi

Bu iş bir insan kararıdır. Ajan bu kararı veremez.

- Karar sahibi proje sahibi ve hukuk sorumlusudur.
- Teknik sahip Hüseyin Cengiz'dir.
- Hüseyin Cengiz Hetzner ile teknik konuları konuşur.

## Neden bu kapı var

Hetzner Almanya merkezli bir sunucu şirketidir. Türkiye'deki kişinin verisi Hetzner'e gidince yurt dışına aktarılmış sayılır. KVKK'nın 9. maddesi bu aktarım için uygun bir güvence ister. Açık rıza yalnız ara sıra yapılan aktarımda geçerlidir. Bizim aktarımımız düzenlidir.

## Adımlar

1. Proje sahibi Hetzner'e resmî bir soru gönderir.
2. Soru şudur: "KVKK standart sözleşmesini imzalar mısınız?"
3. Hüseyin Cengiz bu yazışmada teknik soruları yanıtlar.
4. Hukuk sorumlusu Hetzner'in yanıtını değerlendirir.
5. Hetzner imzalamazsa hukuk sorumlusu öteki güvenceleri değerlendirir. Örneğin Kurul izinli taahhütname bir seçenektir.
6. Hukuk sorumlusu bildirim servislerini de değerlendirir. Örneğin Google, Apple ve e-posta sağlayıcısı ayrı yurt dışı alıcılarıdır.
7. Taraflar standart sözleşmeyi imzalarsa proje sahibi imza tarihini kayda yazar.
8. Proje sahibi imzadan sonraki 5 iş günü içinde Kurula bildirim yapar.
9. Proje sahibi kararı proje kaydına yazdırır. Karar boştaki ilk O numarasını alır. Örneğin O-57 artık kullanılıyor.
10. Hüseyin Cengiz AB kullanıcılarının verisini Hetzner'in AB veri merkezinde tutar.

Bildirim yapılmazsa para cezası vardır. Ceza 50.000 TL ile 1.000.000 TL arasındadır.

## Bağımlılıklar

- Bu kapı kapanmadan hazırlık sunucusuna gerçek kişi verisi girmez. Hazırlık işi [staging-e2e.md](staging-e2e.md) dosyasındadır.
- Bu kapı kapanmadan üretime dağıtım yapılmaz. Dağıtım işi [release-and-deploy.md](release-and-deploy.md) dosyasındadır.
- Bu kapı kapanmadan da örnek veriyle çalışma sürebilir.

## Doğrulama

Hüseyin Cengiz şu kontrolleri yapar:

1. Proje kaydında güvence kararının yazılı olduğunu görür.
2. Kararda güvence türünü, imza tarihini ve bildirim tarihini görür.
3. Hazırlık sunucusunda yalnız örnek veri olduğunu doğrular. Örneğin kullanıcı adresleri `example.test` ile biter.

Sözleşme metni ve imzalı belge depoya konmaz. Kayıtta yalnız belgenin nerede durduğu yazılır.

## Kabul ölçütü

- Proje sahibi ve hukuk sorumlusu güvenceyi onayladı.
- Onay proje kaydında yazılı.
- Kurula bildirim 5 iş günü içinde yapıldı.
- Gerçek kişi verisi bu onaydan önce Hetzner'e girmedi.
