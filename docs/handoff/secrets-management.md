# Sır yönetimi

## Kapsam

Bu not G-112 gereksinimini kapsar.
Sır, erişim veren parola veya anahtar gibi gizli bilgidir.
G-49 yedek anahtarları için [yedek notuna](offsite-backup.md) bakın.

## Görev sahibi

Hüseyin Cengiz sırların yerini, erişimini ve yenilenmesini doğrular.

## Bağımlılıklar

Press, Jenkins ve deneme ortamının sunucusu hazır olmalıdır.
Deneme ortamı beta ya da rc ortamıdır. Ç-4 kararına göre "staging" adı kullanılmaz.
Jenkins, sürüm paketini derleyen ve sunucuya taşıyan otomatik sistemdir.
Kimlik eşitleme servisi, test giriş sistemiyle çalışmalıdır.
Yetkili operatörün özel ağ erişimi hazır olmalıdır.

## Sırların yeri

Depoda sır yoktur. Sırlar üç yerde durur:

1. Press sırları Press'teki “Password” türündeki alanlarda durur.
2. Jenkins'in SSH anahtarları ve imaj deposu tokeni Jenkins kimlik kayıtlarında durur.
3. Uygulama sırları sunucuda `/etc/atonota/<ortam>/<servis>.env` dosyalarında durur.

Jenkins kayıtlarının adları [Jenkins kimlik notundadır](jenkins-credentials.md).
Sunucu dosyalarının listesi [ortam notunun sırlar bölümündedir](../dagitim/ortamlar.md).
Her dosyanın anahtar listesi `deploy/settings/` klasöründedir.
Örneğin yedek ayarlarının listesi `deploy/settings/offsite.production.env.example` dosyasındadır.
Bu listelerde yalnız anahtar adı ve değer biçimi vardır. Gerçek değer yoktur.

## Adımlar

1. Hüseyin Cengiz Press sırlarını “Password” türündeki alanlara koyar.
2. Hüseyin Cengiz Jenkins kimlik kayıtlarını açar ve değerleri girer.
3. Hüseyin Cengiz her ortamın sır dosyalarını sunucuya yazar.
4. Hüseyin Cengiz her sır dosyasının iznini `0600` yapar.
5. Hüseyin Cengiz dosyanın sahibini o ortamın dağıtım kullanıcısı yapar.
6. Hüseyin Cengiz sunucu erişimini özel ağla sınırlar.
7. Hüseyin Cengiz her ortam için ayrı SSH anahtarı kullanır.
8. Hüseyin Cengiz anahtar yenileme planını kaydeder.

Örneğin alpha sır dosyalarının sahibi `deploy-alpha` kullanıcısıdır.
Her ortamın sırları ayrıdır. alpha parolası prod ortamında kullanılmaz.
Jenkins uygulama sırlarını görmez. Jenkins yalnız sunucuya bağlanır ve imaj yükler.
Eşitleme servisinin Keycloak istemci sırrı iki dosyada durur.
Bu dosyalar `keycloak.env` ve `identity-sync.env` dosyalarıdır.
Hüseyin Cengiz iki dosyaya aynı değeri yazar.
Anahtar adları `deploy/settings/identity-sync.production.env.example` dosyasındadır.
Hüseyin Cengiz iyzico, Anthropic ve SMTP anahtarlarını 90 günlük plana alır.
SMTP, e-posta göndermek için kullanılan bir yöntemdir.
SSH, sunucuya güvenli giriş yöntemidir.

## Doğrulama

1. Hüseyin Cengiz Gitleaks sır taramasının çalıştığını doğrular.
2. Hüseyin Cengiz Jenkins'teki depo taramasının sonucunu kontrol eder.
3. Hüseyin Cengiz yetkili hesabı deneme ortamında dener.
4. Hüseyin Cengiz yetkisiz hesabın erişemediğini doğrular.
5. Hüseyin Cengiz sırların korunan alanlarda durduğunu doğrular.
6. Hüseyin Cengiz 90 günlük yenileme planını kontrol eder.

Gitleaks, depoya yazılmış sırları arayan araçtır.
Taramayı `dev/bin/security-audit` betiği başlatır.
Tarama komutları [CI güvenlik notundadır](ci-security.md).

## Kabul ölçütü

Depoda sır bulunmaz. İki taramanın sonucu kayda girer.
Kanıt, yetkili erişimi ve yetkisiz erişimin reddini gösterir.
Kanıt, korunan alanları ve 90 günlük yenileme planını gösterir.
Kanıtta sır değeri yer almaz.

Bu not doğrulama adımlarını kaydeder. Deneme ortamındaki deneme bekliyor.
