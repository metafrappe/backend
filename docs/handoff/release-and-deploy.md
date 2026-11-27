# Yayın onayı ve üretime dağıtım

Bu not yayın onayını, üretime dağıtımı ve geri almayı anlatır. Not 23 Kasım 2026 Pazartesi günü yazıldı. Not 28 Kasım 2026 Cumartesi günü bu depoya taşındı. Bilgiler aynı gün `main` dalıyla karşılaştırıldı.

## Kapsam

- Bu not denetim raporunun 5. bölümündeki 21. ve 22. işi kapsar.
- 21. iş yayın onayıdır. 22. iş üretime dağıtımdır.
- Yayın onayı G-50, G-113, G-142 ve G-151 kanıtlarına bakar.
- Dağıtım tasarımı [ortamlar belgesindedir](../dagitim/ortamlar.md). Kod `deploy/` klasöründedir.

## Görev sahibi

- 21. iş bir insan kararıdır. Karar sahibi proje sahibidir.
- Gerçek kişi verisi için hukuk sorumlusunun onayı da gerekir. Ayrıntı [data-assurance-gate.md](data-assurance-gate.md) dosyasındadır.
- 22. işin görev sahibi Hüseyin Cengiz'dir.
- DNS kayıtlarını Asistan Hüseyin GoDaddy'de uygular.

## Yayın onayı adımları

1. Hüseyin Cengiz açık borçların listesini proje kaydından çıkarır.
2. Hüseyin Cengiz dört kanıtı listeye ekler. Kanıtlar kapasite, izleme, güvenlik ve uçtan uca sınamadır.
3. Proje sahibi listeyi okur.
4. Proje sahibi bütün borçlar kapandıysa yayına onay verir.
5. Proje sahibi onayı yazılı verir. Onay proje kaydına yazılır.

## Dağıtım adımları

1. Hüseyin Cengiz sunucudaki sır dosyalarını hazırlar. Sırlar `/etc/atonota/prod/` klasöründe durur.
2. Hüseyin Cengiz anahtar listesinin tam olduğunu denetler. Liste `deploy/settings/` klasöründedir.
3. Hüseyin Cengiz prod için sunucu dışı yedek ayarını hazırlar. Ayar yoksa dağıtım betiği durur.
4. Hüseyin Cengiz paketin rc ortamında sağlıklı olduğunu görür.
5. Hüseyin Cengiz Jenkins'te yükseltme işini açar. İşin tanımı `deploy/jenkins/promote.Jenkinsfile` dosyasındadır.
6. Hüseyin Cengiz `ACTION` değerini `promote`, `ENVIRONMENT` değerini `prod` seçer.
7. Hüseyin Cengiz önce `KIND` değerini `backend` seçer ve işi çalıştırır.
8. prod işinde onayı `atonota-release-managers` grubundan biri verir.
9. Jenkins prod'da yedek alır, veritabanını taşır ve servisleri başlatır.
10. Jenkins sağlık denetimini çalıştırır.
11. Arka uç sağlıklıysa Hüseyin Cengiz `KIND` değerini `web` seçer ve işi yeniden çalıştırır.

İlk kurulumda çalışan sürüm yoktur. Bu durumda betik yalnız `ATONOTA_FIRST_INSTALL=1` ile çalışır. Ortamlar belgesi ilk kurulum adımları için bir devir notuna işaret eder. Bu not 28 Kasım 2026 Cumartesi günü de depoda yoktu. Hüseyin Cengiz ilk kurulumdan önce bu notu yazdırmalıdır.

## Geri alma adımları

Sağlık denetimi başarısız olursa Jenkins yalnız başarısız paketi geri alır. Sağlıklı paket geri alınmaz. prod'da Jenkins yedeği kendiliğinden geri yüklemez.

Bir kişi geri almak isterse şu adımları izler:

1. Hüseyin Cengiz paketin `phase` dosyasındaki aşamayı okur.
2. Aşama `preparing` ya da `pulling` ise hiçbir şey yapmaz. Eski paket zaten çalışır.
3. Öteki aşamalarda Hüseyin Cengiz Jenkins'te yükseltme işini açar.
4. Hüseyin Cengiz `ACTION` değerini `rollback`, `ENVIRONMENT` değerini `prod` seçer.
5. Hüseyin Cengiz `KIND` değerini geri alınacak pakete göre seçer: `backend` ya da `web`.
6. Jenkins önceki paketi yeniden başlatır.
7. Veritabanı yeni pakete uymuyorsa Hüseyin Cengiz yedeği geri yükleme kararını verir.
8. Yedek geri yüklenirse yedekten sonra yazılan veri silinir. Hüseyin Cengiz bu kaybı önce proje sahibine onaylatır.
9. Onaydan sonra Hüseyin Cengiz `ACTION` değerini `rollback-restore` seçer.
10. Hüseyin Cengiz sağlık denetimini yeniden çalıştırır.

Taşıma yarım kaldıysa aynı paket yeniden taşınmaz. Aşama `migrating`, `migrated` ya da `starting` ise Hüseyin Cengiz `resume` seçebilir. Bunun yerine `rollback-restore` da seçebilir. Bu iki seçenek yalnız `backend` paketinde çalışır.

Jenkins'in dışındaki komut biçimi şudur:

```sh
deploy/bin/rollback prod backend --failed <paket kimliği>
deploy/bin/rollback prod backend --restore-backup
```

## Bağımlılıklar

- Veri güvencesi kapanmış olmalı: [data-assurance-gate.md](data-assurance-gate.md).
- Uçtan uca sınama geçmiş olmalı: [staging-e2e.md](staging-e2e.md).
- Kapasite ve izleme kurulmuş olmalı: [capacity-monitoring.md](capacity-monitoring.md).
- Güvenlik kararları kayıtta olmalı: [security-advisories.md](security-advisories.md).
- CI güvenlik kapısı kurulmuş olmalı: [ci-security.md](ci-security.md).
- `atonota.net` DNS kayıtları uygulanmış ve doğrulanmış olmalı.
- Proje sahibinin yazılı yayın onayı alınmış olmalı.

## Doğrulama

1. Dağıtım testleri depo kökünde geçmeli: `python3 -I -m unittest discover -s deploy/tests`.
2. Sunucu betiği testleri yalnız Linux'ta koşar. macOS sonucu kanıt sayılmaz.
3. Sağlık denetimi prod paketini dışarıdan HTTPS ile sınar: `deploy/bin/health prod <paket klasörü>`.
4. Sağlık kaydı sunucuya yazılmış olmalı.
5. Geri alma bir kez rc ortamında denenmiş olmalı.

## Kabul ölçütü

- Proje sahibinin yayın onayı proje kaydında yazılı.
- prod'da arka uç ve arayüz paketi sağlık denetimini geçti.
- prod için sunucu dışı yedek alındı.
- Geri alma adımı rc ortamında denendi ve sonucu kayıtta.
- Notlarda ve kayıtlarda sır değeri yok.
