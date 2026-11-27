# Gizli değerler: tarama, şifreli ortam dosyası ve anahtar yenileme

Bu belge G-112 gereksinimini anlatır. Parola, API anahtarı ve belirteç birer gizli değerdir. Gizli değerler depoya girmez. Sunucunun ortam dosyası şifreli saklanır.

Belgede üç konu var:

1. Commit öncesi tarama
2. sops ve age ile şifreli ortam dosyası
3. 90 günde bir anahtar yenileme

Testler `dev/tests/test_secret_hygiene.py` dosyasındadır. Testi şu komut koşar:

```bash
python3 -I dev/tests/test_secret_hygiene.py
```

## 1. Commit öncesi tarama

Tarama aracı gitleaks'tir. gitleaks, commit'e girecek değişikliği okur. Değişiklikte gizli değer bulursa commit'i durdurur.

Kanca iki uygulamanın `.pre-commit-config.yaml` dosyasındadır:

- `apps/platform_core/.pre-commit-config.yaml`
- `apps/press_tr/.pre-commit-config.yaml`

Kancanın sürümü `dev/security/tool-versions.env` dosyasındaki `GITLEAKS_VERSION` değeriyle aynıdır. Sürüm değişince iki yeri birlikte değiştirin. Test farkı yakalar.

### Kancayı bağlama

Kancayı bir kez bağlayın. Adımlar şöyledir:

1. `pre-commit` aracını kurun. Örneğin `pipx install pre-commit` komutunu çalıştırın.
2. Deponun kökünde `dev/bin/install-secret-hook` komutunu çalıştırın.

Betik yalnız deponun kendi `pre-commit` kancasını yazar. Bu dosya `.git/hooks/pre-commit` yolundadır.

Betik `core.hooksPath` ayarını değiştirmez. Kişisel Git yazar koruması bu ayardadır. Koruma önce deponun kancasını çalıştırır. Sonra yazar kimliğini denetler. Böylece iki denetim birlikte çalışır.

`pre-commit install` komutunu kullanmayın. Bu komut `core.hooksPath` ayarı varken çalışmaz.

Depoda başka bir `pre-commit` kancası varsa betik durur. Bu durumda gitleaks çağrısını o kancaya elle ekleyin.

`--no-verify` kullanmayın. Kanca yanlış alarm verirse bulguyu inceleyin. İnceleme bitince bulgunun parmak izini `dev/security/.gitleaksignore` dosyasına yazın. Dosyaya sorumlu rolü ve gerekçeyi de yazın.

### Ek tarama

Kanca yalnız yeni değişikliği tarar. Git geçmişinin tamamını `dev/security/history-scan` tarar. Bu tarama güvenlik kapısının parçasıdır.

## 2. Şifreli ortam dosyası: sops ve age

sops, bir dosyadaki değerleri şifreler. Anahtar adları okunur kalır. age ise şifreleme anahtarını üretir.

age anahtarının iki yarısı vardır:

- Açık yarı `age1` ile başlar. Herkes görebilir. Dosyayı şifrelemeye yarar.
- Özel yarı `AGE-SECRET-KEY-1` ile başlar. Dosyayı açmaya yarar. Özel yarı depoya hiç girmez.

### Dosyalar

- `.sops.yaml` dosyası şifreleme kuralını tutar. Kural `deploy/secrets/` klasöründeki `*.sops.env` dosyalarına uyar.
- `deploy/secrets/example.sops.env` dosyası örnektir. Değerleri uydurmadır ve şifrelidir.
- `deploy/secrets/` klasörüne şifresiz dosya konmaz. Test bunu denetler.

Örnek dosyanın anahtarı yalnız bu örnek için üretildi. Anahtarın özel yarısı şifrelemeden sonra silindi. Bu yüzden örnek dosya açılamaz. Dosya yalnız biçimi gösterir.

### Şifreleme ve açma

Gerçek anahtarla şu adımları DevOps sorumlusu uygular:

1. `age-keygen -o age.key` komutuyla anahtar üretin. Özel anahtarı parola kasasına koyun.
2. Açık yarıyı `.sops.yaml` dosyasındaki kurala ekleyin.
3. Şifresiz dosyayı depo dışında hazırlayın.
4. Dosyayı şifreleyin:

   ```bash
   sops encrypt --filename-override deploy/secrets/<ortam>.sops.env \
       --input-type dotenv --output-type dotenv <düz-dosya> > <ortam>.sops.env
   ```

5. Şifresiz dosyayı silin.
6. Sunucuda dosyayı açın. Çıktıyı `/etc/atonota/<ortam>/<servis>.env` yoluna yazın:

   ```bash
   umask 077
   SOPS_AGE_KEY_FILE=<özel-anahtar> sops decrypt <ortam>.sops.env > /etc/atonota/<ortam>/<servis>.env
   ```

Dosya izni `0600` olur. Sahip ve izin kuralı [ortamlar belgesindedir](ortamlar.md).

### Bu işin dışında kalanlar

- Bu iş canlı sunucuya dokunmaz.
- Gerçek ortamın age anahtarını bu iş üretmez.
- Gerçek ortamın şifreli dosyası bu depoya eklenmedi.
- Dağıtım betiği dosyayı henüz kendiliğinden açmaz. Bu bağlantı ayrı bir iştir.

## 3. Anahtar yenileme: 90 gün

Aşağıdaki anahtarlar 90 günde bir yenilenir. Anahtar sızdıysa yenilemeyi hemen yapın. 90 günü beklemeyin.

| Anahtar | Ne işe yarar | Nereden yenilenir |
| --- | --- | --- |
| `IYZICO_API_KEY` | iyzico ödeme API'sinin anahtarıdır | iyzico üye işyeri paneli |
| `IYZICO_SECRET_KEY` | iyzico isteğini imzalar | iyzico üye işyeri paneli |
| `MODEL_PROVIDER_API_KEY` | Her model sağlayıcı için ayrı anahtardır | İlgili model sağlayıcı paneli |
| `SMTP_PASSWORD` | E-posta gönderen hesabın parolasıdır | SMTP hizmetinin paneli |

iyzico anahtarları çift olarak yenilenir. API anahtarı ile gizli anahtar birlikte değişir.

Birden çok model sağlayıcı varsa her birinin anahtarını ayrı yenileyin.

### Yenileme adımları

Her anahtar için DevOps sorumlusu şu sırayı izler:

1. Sağlayıcı panelinde yeni anahtar üretin. Eski anahtarı henüz kapatmayın.
2. Şifreli ortam dosyasını `sops edit <ortam>.sops.env` komutuyla açın. Yeni değeri yazın.
3. Değişikliği önce alpha ortamında deneyin. Örneğin iyzico deneme ortamında bir ödeme deneyin.
4. Sonuç doğruysa sırayla beta, rc ve prod ortamına taşıyın.
5. Prod çalışınca eski anahtarı sağlayıcı panelinde kapatın.
6. Yenileme tarihini ve yapan kişiyi kayda yazın. Bir sonraki tarih, bu tarihten sonraki 90. gündür.

Yeni anahtarı commit mesajına, yoruma ve rapora yazmayın.

### age anahtarını değiştirme

age anahtarı sızdıysa şu adımları izleyin:

1. Yeni age anahtarı üretin.
2. `.sops.yaml` dosyasındaki açık yarıyı değiştirin.
3. `sops updatekeys <ortam>.sops.env` komutunu çalıştırın.
4. Dosyadaki bütün anahtarları da yenileyin. Eski age anahtarı dosyanın eski kopyalarını açabilir.
