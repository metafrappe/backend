# Uyarı runbook'u

Bu belge her izleme uyarısında ne yapılacağını anlatır. Gereksinim G-113'tür.

## Amaç

İzleme sistemi bir sorun görünce uyarı gönderir. Uyarıyı alan kişi bu belgede uyarının adını bulur. Sonra o bölümdeki adımları uygular.

Uyarı kuralları şu dosyalardadır:

- `deploy/monitoring/prometheus/alerts.rules.json`
- `deploy/monitoring/prometheus/capacity.rules.json`

Dış erişim denetimleri `deploy/monitoring/uptime-checks.json` dosyasındadır. Hata izleme ayarı `deploy/monitoring/error-tracking.json` dosyasındadır.

## Görev sahibi

Hüseyin Cengiz bu runbook'un sahibidir. Uyarıları Hüseyin Cengiz alır ve çözer.

## Ön koşullar

1. Prometheus, Alertmanager, node_exporter, cAdvisor ve blackbox_exporter kuruludur. Kurulum devir notundadır: `docs/handoff/g113-g114-monitoring-backup.md`.
2. Hüseyin Cengiz sunucuya bağlanabilir.
3. Uyarının ortamı ve sunucusu bilinir. Uyarı bu bilgiyi etiketlerinde taşır.

## Adımlar

Önce uyarının adını aşağıda bulun. Sonra o bölümün adımlarını uygulayın. Hiçbir container'ı nedenini bilmeden yeniden başlatmayın.

### `InstanceDown`

1. Sunucuya bağlanmayı deneyin.
2. Sunucu yanıt vermiyorsa sağlayıcının panelinden durumu okuyun.
3. Sunucu kaybolduysa `deploy/runbooks/disaster-recovery.md` belgesini uygulayın.
4. Yalnız ölçüm aracı durduysa aracın logunu okuyun. Sonra aracı başlatın.

### `UptimeProbeFailed`

1. Hangi denetimin düştüğünü `check` etiketinden okuyun.
2. Sunucuda `status` betiğini çalıştırın. Bütün container'lar sağlıklı olmalıdır.
3. Sorun yeni bir sürümle başladıysa `deploy/runbooks/rollback.md` belgesini uygulayın.

### `CertificateExpiresSoon`

1. Caddy container'ının logunu okuyun. Sertifika yenileme hatasını bulun.
2. Hata DNS kaydındaysa doğru kaydı yazın. Kaydı Asistan Hüseyin GoDaddy'de girer.

### `ContainerRestarting`

1. Container'ın logunu okuyun.
2. Bellek yetmiyorsa `MemoryLow` bölümüne bakın.
3. Sorun yeni bir sürümle başladıysa geri dönüşü düşünün.

### `AvailabilityBudgetBurn`

1. Aylık hedef yüzde 99,5 kullanılabilirliktir. Bu hedef G-113'ün önerisidir.
2. Hangi ortamın etkilendiğini `env` etiketinden okuyun.
3. Aynı anda açık olan `UptimeProbeFailed` uyarısını çözün.

### `DiskSpaceLow`

1. Diskte en çok yer kaplayan klasörleri bulun. Örnek: `du -xh /srv/atonota | sort -h | tail`.
2. Sunucu dışına kopyalanmış eski yedekleri sunucudan silin. Kopyanın sağlam olduğunu önce denetleyin.
3. Kullanılmayan imajları silin. Çalışan sürümün imajına dokunmayın.

### `DiskSpaceCritical`

1. `DiskSpaceLow` adımlarını hemen uygulayın.
2. Yer açılamazsa diski büyütün. Veritabanı disk dolunca yazmayı durdurur.

### `MemoryLow`

1. En çok bellek kullanan container'ı bulun. Örnek: `docker stats --no-stream`.
2. İşçi sayılarını `docs/dagitim/ortamlar.md` belgesindeki hesapla karşılaştırın.

### `BackupMissing`

1. `deploy/runbooks/backup.md` belgesinin adımlarıyla elle yedek alın.
2. Düzenli yedek neden çalışmadı, sunucu logundan bulun.

### `OffsiteBackupMissing`

1. Yedek betiğinin `rclone` çıktısını okuyun.
2. Object Storage erişimini denetleyin. Erişim bilgisini hiçbir yere yazmayın.

### `DiskWillFillSoon`

1. Diskin dolma hızını grafikte okuyun.
2. Eski yedekleri temizleyin ya da disk büyütmeyi planlayın.

### `CpuSaturated`

1. En çok işlemci kullanan container'ı bulun.
2. Çekirdek payları doğrulanmadı. Ölçümü `docs/dagitim/ortamlar.md` belgesine yazın.

## Doğrulama

1. Uyarı izleme sisteminde kapanmalıdır.
2. Sorun bir sürümden geldiyse çözümü göreve yazın.
3. Uyarı yanlış alarm verdiyse eşiği kural dosyasında değiştirin. Değişiklik testten geçmelidir.
