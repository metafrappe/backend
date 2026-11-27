# G-113 ve G-114 izleme ve yedek kurulumu

Bu not canlı adımları anlatır. Adımları Hüseyin Cengiz uygular. Hüseyin Cengiz kıdemli DevOps mühendisidir. Adımlar önce deneme ortamında denenir.

Depoda yalnız kural dosyaları ve runbook'lar vardır. Bu dosyalar henüz hiçbir sunucuda çalışmadı.

## Depodaki dosyalar

- Uyarı kuralları: `deploy/monitoring/prometheus/alerts.rules.json`
- Kapasite kuralları: `deploy/monitoring/prometheus/capacity.rules.json`
- Dış erişim denetimleri: `deploy/monitoring/uptime-checks.json`
- Hata izleme ayarı: `deploy/monitoring/error-tracking.json`
- Runbook'lar: `deploy/runbooks/`
- Testler: `deploy/tests/test_monitoring_rules.py` ve `deploy/tests/test_runbooks.py`

Kural dosyaları JSON biçimindedir. Prometheus kural dosyasını YAML olarak okur. JSON da geçerli YAML'dir. Bu yüzden dosyalar olduğu gibi yüklenir.

## Canlı adımlar

Görev sahibi her adımda Hüseyin Cengiz'dir. DNS adımında Asistan Hüseyin de görev alır.

1. İzleme sunucusunu kurun. Sunucuda Prometheus, Alertmanager ve Grafana çalışır. Press Monitor Server bu iş için kullanılabilir.
2. Her ortam sunucusuna node_exporter ve cAdvisor kurun. Portları yalnız izleme sunucusuna açın.
3. Ortam sunucusunun dışında bir blackbox_exporter kurun. Görevin adı `uptime` olur. Denetim yollarını `uptime-checks.json` dosyasından alın. Adresi `release.py env-show <ortam>` komutu verir.
4. Her hedefe `env` etiketi verin. Değer `alpha`, `beta`, `rc` ya da `prod` olur.
5. İki kural dosyasını Prometheus'un `rule_files` listesine ekleyin. Sonra `promtool check rules` ile denetleyin.
6. Alertmanager'ın gönderim yerini seçin. Gönderim adresi gizli bilgidir. Adresi depoya yazmayın.
7. Yedek betiğine bir ölçüm ekleyin. Betik başarıyla bitince node_exporter'ın textfile klasörüne iki değer yazmalıdır: `platform_backup_last_success_timestamp_seconds` ve `platform_offsite_backup_last_success_timestamp_seconds`. Her değer `env` etiketini taşır. Bu değişiklik ayrı bir geliştirme işidir.
8. GlitchTip'i kendi sunucunuzda kurun. `FRAPPE_SENTRY_DSN` ve `SENTRY_ENVIRONMENT` değerlerini sunucudaki `tenant.env` dosyasına yazın. Press açıksa değeri Release Group `environment_variables` alanına yazın.
9. GlitchTip'te kişisel veri temizliğini açın. Temizlenecek alanlar `error-tracking.json` dosyasının `scrub` listesindedir.
10. Log sunucusunu kurun. Press Log Server, Elasticsearch ve Kibana kullanır. `X-Request-Id` değeri log ve izlerde ortak olmalıdır.
11. Sertifika uyarısı DNS sorununu gösterirse kaydı Hüseyin Cengiz yazar. Asistan Hüseyin kaydı GoDaddy'de girer.

## Yedek için açık işler

G-114'ün şu parçaları depoda yoktur:

- Press veritabanının yedeği,
- Press agent veritabanının yedeği,
- imaj deposunun (Registry) yedeği,
- yedeğin şifrelenmesi,
- Press ve Keycloak için binlog ve WAL kopyası. Bu kopya 1 saatlik RPO için gerekir.

Hüseyin Cengiz bu parçaların tasarımını yazar. Kod gereken parça için PO'ya yeni iş açılır.

## Kabul

1. `promtool check rules` iki dosya için hata vermez.
2. Deneme ortamında bir container durdurulur. `UptimeProbeFailed` uyarısı gelir.
3. Deneme ortamında disk eşiği geçici olarak düşürülür. `DiskSpaceLow` uyarısı gelir. Eşik sonra eski değerine döner.
4. Deneme ortamında bir hata üretilir. Hata GlitchTip'te görünür. Hatada e-posta ve çerez görünmez.
5. İlk DR tatbikatı `deploy/runbooks/disaster-recovery.md` belgesine göre yapılır. Ölçülen RTO göreve yazılır.
