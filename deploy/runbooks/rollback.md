# Geri dönüş runbook'u

Bu belge bir ortamı önceki sürüme döndürmeyi anlatır. Geri dönüşün İngilizce adı rollback'tir. Gereksinim G-114'tür.

## Amaç

Yeni sürüm hata verebilir. Bu durumda ortam önceki sürüme döner. Gerekirse veri, sürümden önceki yedekten geri gelir.

Ayrıntılı tasarım `docs/dagitim/ortamlar.md` belgesindedir.

## Görev sahibi

Hüseyin Cengiz bu runbook'un sahibidir. Geri dönüşe Hüseyin Cengiz karar verir.

## Ön koşullar

1. Hata gerçektir. Örneğin dış sağlık denetimi düşmüştür.
2. Geri alınacak paketin kimliği bilinir.
3. Veri geri yüklenecekse sürümden önceki yedek vardır.

## Adımlar

### Arka uç ve arayüz paketi

1. Jenkins'te `promote.Jenkinsfile` işini açın. İş `deploy/jenkins/promote.Jenkinsfile` dosyasındadır.
2. "ACTION" alanında `rollback` seçin. Veri de geri gelecekse `rollback-restore` seçin.
3. "ENVIRONMENT" ve "KIND" alanlarını seçin.
4. Onay adımında işi onaylayın.

Jenkins işi `deploy/bin/rollback` betiğini çalıştırır. Elle çalıştırmanın biçimi şudur:

```sh
deploy/bin/rollback <ortam> <backend|web> [--failed <paket kimliği>] [--restore-backup]
```

`--restore-backup` yalnız arka uçta çalışır. Bu seçenek geri alınan paketten önceki yedeği yükler.

Paket `migrating` aşamasında kaldıysa veritabanı yarım taşınmış olabilir. Bu durumda `--restore-backup` olmadan ortam bakım kipinde kalır. Kararı Hüseyin Cengiz verir.

### Press tarafı

Press açık değilse bu bölümü atlayın.

1. Bench'i geri almak için Press'te önceki "Deploy Candidate" kaydını seçin. Siteleri o bench'e "Site Update" ile taşıyın.
2. Siteyi yedekten geri yüklemek için Press'in geri yükleme işlemini kullanın.
3. Press agent güncellemesi hata verirse `auto_rollback` açık olmalıdır. Agent kendi önceki sürümüne döner.

### Keycloak

1. Keycloak sürümü arka uç paketinin içindedir. Arka uç geri dönüşü Keycloak'ı da önceki imaja döndürür.
2. Keycloak veritabanı yeni sürümde değiştiyse `rollback-restore` seçin. Eski Keycloak yeni şemayla açılmayabilir.

## Doğrulama

1. Sunucuda `status` betiği önceki paketin kimliğini yazmalıdır.
2. `deploy/bin/health <ortam> <sürüm klasörü>` başarılı olmalıdır.
3. İzleme sisteminde `UptimeProbeFailed` uyarısı kapanmalıdır.
4. Geri alınan paket "failed" bağına yazılmalıdır. Bu paket ikinci geri dönüşte seçilmez.
