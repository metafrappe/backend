# Başka konumda yedek

## Kapsam

Bu not G-5 ve G-49 gereksinimlerini kapsar.
Denetim raporunun 15, 16 ve 17 numaralı işleri DNS'i kapsar.
Bu işler için [DNS notuna](dns-records.md) bakın.

## Görev sahibi

Hüseyin Cengiz yedek ayarlarını ve geri yüklemeyi doğrular.

## Bağımlılıklar

Deneme ortamında Press ve bir test sitesi çalışmalıdır.
Deneme ortamı beta ya da rc ortamıdır. Hüseyin Cengiz ortamı seçer.
Ç-4 kararına göre bu notta "staging" adı kullanılmaz.
Press, kiracı sitelerini kuran ve yöneten uygulamadır.
İki ayrı depolama konumu hazır olmalıdır.
Hüseyin Cengiz gerekli erişimleri [sır yönetimi notuna](secrets-management.md) göre alır.

Aşağıdaki üç kod işi yazıldı. Üçü de `main` dalındadır.

1. Agent yaması yazıldı. G-5 bu yamayı ister.
   - Yama `deploy/images/agent-patches/0001-offsite-s3-endpoint.patch` dosyasındadır.
   - Yamanın açıklaması [yama klasörünün README dosyasındadır](../../deploy/images/agent-patches/README.md).
   - Yama, Agent'ın Press'ten gelen depolama adresini okumasını sağlar.
   - Testi `deploy/tests/test_agent_patches.py` dosyasındadır.
   - Bu depoda Agent imajı yoktur. Hüseyin Cengiz yamayı deneme ortamındaki Agent'a uygular.
2. Sürüm yedeği dış konuma kopyalanır. G-5 bu kopyayı da ister.
   - Betik `deploy/remote/backup` dosyasıdır.
   - Betik kiracı sitelerini, Keycloak veritabanını ve eşitleme servisinin veritabanını yedekler.
   - Betik yedeği `rclone` ile Hetzner Object Storage kovasına kopyalar. Sonra kopyayı denetler.
   - Kova ayarları sunucuda `/etc/atonota/<ortam>/offsite.env` dosyasındadır.
   - Bu dosyanın anahtar listesi `deploy/settings/offsite.production.env.example` dosyasındadır.
   - rc ve prod ortamında bu dosya zorunludur. Dosya yoksa yedek başarısız olur.
   - alpha ve beta ortamında dosya isteğe bağlıdır.
3. Anahtar biçimi denetimi yazıldı. G-49 bu denetimi ister.
   - Denetim `apps/press_tr/press_tr/backup_keys.py` dosyasındadır.
   - Denetim, `press_tr` uygulamasında Site kaydı kaydedilirken çalışır.
   - Geçersiz biçimli anahtar Site kaydını durdurur. Hata mesajı anahtar değerini yazmaz.
   - Testi `apps/press_tr/tests/test_backup_keys.py` dosyasındadır.

Hüseyin Cengiz 3. adımı ve 6. doğrulama adımını bu kodla yapar.
Sürüm yedeğinin ayrıntıları [ortam notunun yedek bölümündedir](../dagitim/ortamlar.md).

## Adımlar

1. Hüseyin Cengiz Press'te yedek depolama alanını tanımlar.
2. Hüseyin Cengiz test planında dış konuma yedeklemeyi açar.
3. Hüseyin Cengiz Agent yamasını test eder.
4. Hüseyin Cengiz kiracı sitesinde `System Settings.encrypt_backup=1` ayarını açar.
5. Hüseyin Cengiz yedeği deneme ortamında ikinci konuma kopyalar.
6. Hüseyin Cengiz yedek saklama kurallarını doğrulama listesine yazar.
7. Hüseyin Cengiz Press veritabanı yedeğini ayrı bir dizine alır.
8. Hüseyin Cengiz Press yedeğini şifreli olarak iki konumda tutar.

Agent, Press'in yedeği yükleyen parçasıdır.
Yama, Agent'ın Hetzner depolama adresini kullanmasını sağlar.
Ana konum `fsn1` olur. İkinci konum `nbg1` olur.
Saklama planı 7 günlük, 4 haftalık ve 12 aylık kopya içerir.
Plan ayrıca yılda bir alınan 10 kopyayı içerir.

## Anahtarın yeri

Press, yedek anahtarını “Site Configuration” ekranında tutar.
Anahtarın alan adı `backup_encryption_key` olur. Alan türü “Password” olur.
Press, uygulamanın Fernet anahtarını da ayrı bir Password alanında tutar.
Fernet, uygulamanın kayıtlı gizli alanlarını şifreler.
Hüseyin Cengiz Press veritabanı yedeğini age veya KMS ile şifreler.
age bir şifreleme aracıdır. KMS bir anahtar yönetim hizmetidir.
Press veritabanı yedeğinin kendi anahtarı vardır.
Bu anahtarın yeri henüz seçilmedi. Depoda bu konuda bir karar yoktur.
G-49'a göre kararı DevOps sorumlusu Hüseyin Cengiz verir.
Hüseyin Cengiz iki seçenekten birini seçer:

1. age kullanılırsa anahtar Press sunucusunun dışında saklanır. Yer adı karara yazılır.
2. KMS kullanılırsa anahtar seçilen KMS hizmetinde durur. Hizmetin adı karara yazılır.

Her iki seçenekte anahtar yedek dosyasıyla aynı yerde tutulmaz.
Hüseyin Cengiz kararı yazmadan 7. ve 8. adımları yapmaz.

## Doğrulama

1. Hüseyin Cengiz örnek veriden 5 GB üzeri yedek alır.
2. Hüseyin Cengiz yedeğin ana konuma yüklendiğini doğrular.
3. Hüseyin Cengiz yedeği Press'in “Remote File” bağlantısından indirir.
4. Hüseyin Cengiz ikinci konumdaki kopyayı doğrular.
5. Hüseyin Cengiz saklama kurallarını test kayıtlarıyla karşılaştırır.
6. Hüseyin Cengiz anahtar biçimi testinin geçtiğini doğrular.
7. Hüseyin Cengiz şifreli yedeği doğru anahtarla test ortamına yükler.
8. Hüseyin Cengiz geri gelen örnek veriyi ilk veriyle karşılaştırır.

## Kabul ölçütü

G-5 kanıtı yükleme ve indirme sonucunu içerir.
Kanıt ikinci kopyayı, saklama kurallarını ve Agent yama testini de içerir.
G-49 kanıtı anahtar biçimini ve geri yükleme sonucunu içerir.
Press veritabanı yedeği iki konumda ve kiracı yedeklerinden ayrı görünür.

Bu not doğrulama adımlarını kaydeder. Deneme ortamındaki deneme bekliyor.
