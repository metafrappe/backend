# Alan adı kayıtları

## Kapsam

Denetim raporunun 5. bölümündeki 15, 16 ve 17 numaralı işler.
G-2, kiracı adresini ve güvenli bağlantı belgesini kapsar.
DNS, alan adını doğru sunucuya yönlendirir.
TLS sertifikası, tarayıcının sunucuya güvenli bağlanmasını sağlar.

## Görev sahipleri

Hüseyin Cengiz kayıtları hazırlar ve sonucu doğrular.
Asistan Hüseyin kayıtları GoDaddy'de uygular.

## Bağımlılıklar

Hedef ortamın sunucusu kurulmuş olmalıdır.
Ortamlar alpha, beta, rc ve prod ortamlarıdır. Ç-4 kararına göre "staging" adı kullanılmaz.
Ortam adreslerini [ortam tablosundan](../dagitim/ortamlar.md) alın.
Giriş adresi `api.login.<ortam tabanı>` biçimindedir. Bu kural O-51 kararıdır.
Örneğin prod giriş adresi `api.login.atonota.net` olur.
alpha giriş adresi `api.login.alpha.atonota.net` olur.
Press adresi `press.<ortam tabanı>` biçimindedir.
Kiracı adresleri `<kiracı>.app.<ortam tabanı>` biçimindedir.
Örneğin prod kiracı kök adresi `app.atonota.net` olur.
Jenkins için ayrıca `ci.atonota.net` adı açılır.
Giriş platformlarının dönüş adresleri [giriş platformları notundadır](atonota-login-platforms.md).

## 15. iş: Kayıtları hazırlama

1. Hüseyin Cengiz hedef ortamı belirler.
2. Hüseyin Cengiz her kaydın türünü, adını ve değerini yazar.
3. Hüseyin Cengiz listeyi Asistan Hüseyin'e verir.

MVP'de kayıtlar GoDaddy'de kalır. Ç-2 kararı bunu belirler.
MVP'de her ad kendi sertifikasını alır. Joker sertifika kullanılmaz.
Route 53, Amazon'un DNS hizmetidir.
Sonraki aşamada yalnız kiracı alt alanı için DNS yönetimi devredilir.
Bu aşama açılırsa Hüseyin Cengiz Route 53 bölgesini hazırlar.
NS kayıtları, alanı hangi DNS sunucularının yönettiğini gösterir.
Hüseyin Cengiz bu kayıtları o aşamanın listesine ekler.

## 16. iş: GoDaddy'de uygulama

1. Asistan Hüseyin GoDaddy hesabını açar.
2. Asistan Hüseyin alan adının kayıt yerini doğrular (O-1).
3. Asistan Hüseyin doğru alan adının DNS yönetim ekranını açar.
4. Asistan Hüseyin listedeki kayıt türünü seçer.
5. Asistan Hüseyin listedeki kayıt adını girer.
6. Asistan Hüseyin listedeki hedef değeri girer.
7. Asistan Hüseyin kaydı kaydeder.
8. Asistan Hüseyin kalan kayıtlar için 4. adımdan devam eder.
9. Asistan Hüseyin kayıtların tamamlandığını Hüseyin Cengiz'e bildirir.

Kayıt yeri veya DNS yönetim yeri farklıysa işlem durur.
Asistan Hüseyin farkı Hüseyin Cengiz'e bildirir.
Listedeki bir kayıt ekrandaki kayıtla çelişirse işlem durur.
Asistan Hüseyin çelişen kaydı Hüseyin Cengiz'e bildirir.

GoDaddy çok katlı joker kaydı kabul etmeyebilir. Örneğin `*.app.alpha` böyle bir kayıttır.
Bu risk `docs/dagitim/ortamlar.md` dosyasında E-11 maddesinde yazılıdır.
GoDaddy bu kaydı reddederse Asistan Hüseyin joker kaydı girmez.
Asistan Hüseyin ret mesajını Hüseyin Cengiz'e bildirir.
Hüseyin Cengiz her kiracı için ayrı bir A kaydı listesi hazırlar.
Asistan Hüseyin bu listeyi 4. adımdan başlayarak girer.

## 17. iş: Sonucu doğrulama

1. Hüseyin Cengiz her kaydı `dig <kayıt-adı> <tür> +short` ile sorgular.
2. Hüseyin Cengiz sorgu sonucunu kayıt listesiyle karşılaştırır.
3. Hüseyin Cengiz adresin doğru sunucuya ulaştığını doğrular.
4. DNS doğrulanınca Hüseyin Cengiz TLS sertifikasını alır.
5. Hüseyin Cengiz sertifikayı `curl -sS -o /dev/null https://<adres>/` ile doğrular.
6. Hüseyin Cengiz kayıt ve sertifika sonucunu kanıta ekler.

## Kabul ölçütü

MVP'de kayıtlar GoDaddy'de görünür. Her adres doğru sunucuya ulaşır.
Her adresin TLS sertifikası geçerlidir.
G-2'nin Route 53 kanıtı sonraki aşamada alınır.
Kanıt, `app.atonota.net` için NS sorgusunun Route 53'ü gösterdiğini içerir.
Hüseyin Cengiz o aşamada kiracı alt adreslerini kapsayan sertifikayı da doğrular.

Bu not uygulama adımlarını kaydeder. Canlı uygulama bekliyor.
