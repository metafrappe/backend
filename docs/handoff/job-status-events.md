# G-15 iş durumlarının aktarılması

Bu not AJA-96 işinin yerel geliştirme kaydıdır.
Dal `pc/job-status-events` adını taşır.
Yerel uygulama hazırdır. Sunucu kanıtı eksiktir. G-15 kapanmadı.

## Kararlar

Karar backend kaydında O-57 olarak yazıldı.
Kaynaklar AJA-192 ve AJA-203 görevlerinin karar belgeleridir.
AJA-203 belgesinin üçüncü sürümü esas alındı.

Deploy kaydı durum olayı üretmez.
Derleme, kuyruk ve Bench kendi durum olaylarını üretir.
Kod, Press dosyalarını değiştirmez. Çalışan Press işlevlerini sarmaz.
Yeni zamanlayıcı eklenmez. Panelin `agent_job_update` kanalı korunur.

Kayıt kancası, olay kopyasını kaynak kayıtla aynı işlemde saklar.
Kaynak işlem geri alınırsa olay da geri alınır.
Ağ gönderimi ayrı işte yapılır.

Doğrudan veritabanı yazısı kayıt kancasını çalıştırmaz.
Uzlaştırıcı bu yolda son gözlenen durumu yakalar.
Uzlaştırıcı, kayıt durumunu önceki durumla karşılaştıran koddur.
Ara durumlar kaybolabilir. Alıcı ara durumları varsaymamalıdır.
`capture` alanı kanca için `hook` değerini taşır.
Uzlaştırıcı için aynı alan `reconcile` değerini taşır.

İlk kuyruk olayında `deploy` alanı boş olabilir.
Press, kuyruk kaydını ilişki satırından önce ekler.
İlk olay kuyruk adını, `candidate` ve `group` değerlerini taşır.
Sonraki olay ilişkiyi çözebilir. Önceki olay değiştirilmez.

## İmzalı kanal

Gönderen `press_tr` uygulamasıdır.
Alıcı `platform_core.ai` modülündedir.
Uç şu adrestedir:

```text
/api/method/platform_core.api.press_status.receive
```

Sözleşme `contracts/platform_core-ai.openapi.yaml` dosyasındadır.
İstek HTTPS kullanır. Yöntem POST olur.
Adres sorgu alanı taşımaz. Eski `cmd` yönlendirmesi kullanılmaz.
Gövde, UTF-8 kodlamasında JSON metnidir.
Gönderen `application/octet-stream` içerik türünü kullanır.
Bu tür ham baytları belirtir. Alıcı JSON metnini kendisi çözer.

Frappe, `application/json` gövdesini alıcıdan önce çözmeye çalışır.
Bu yüzden o içerik türü bu kanalın dışındadır.
Bozuk JSON, bu türle gelirse Frappe önce hata verebilir.
Her yanlış içerik türünün 401 alacağı söylenmez.

İmza HMAC-SHA256 kullanır. Bu yöntem ortak gizli anahtarla veri doğrular.
İmzalanan ham veri şöyledir:

```text
timestamp.event_id.raw_body
```

Başlıklar şunlardır:

- `X-Press-Event-Id`
- `X-Press-Timestamp`
- `X-Press-Key-Id`
- `X-Press-Signature`

İmza `v1=<64 küçük onaltılık karakter>` biçimindedir.
Anahtar en az 32 bayt olur.
Alıcı en çok 300 saniyelik saat farkını kabul eder.
Gövde en çok 16.384 bayt olur.

Alıcı imzayı doğruladıktan sonra gövde alanlarını denetler.
Olay `data`, `output`, `traceback` ve ham `payload` alanlarını taşımaz.
Alıcı aynı olay kimliğini ikinci kez yazmaz.
Gönderen başarısız olayı giden kutusunda tutar.
Sonraki mevcut Press tetiği yeniden gönderimi dener.
Aynı gönderimde olay kimliği ve gövde değişmez.

Alıcının işi gelen kutusuna yazınca biter.
Ajanın olayı işlemesi başka bir iştir.
Bu imza Press oturumu açmaz. Müşteri bildirim yetkisi vermez.

## Yapılandırma ve sunucu devri

Hüseyin Cengiz bu bölümü ayrı deneme ortamında uygular.
Hüseyin Cengiz gerçek kişi verisi kullanmaz.
Bu görev çalışan 7400 ortamını değiştirmez.

1. Hüseyin Cengiz kendi deneme ortamının yedeğini alır.
2. Hüseyin Cengiz deneme ortamına bu dalın uygulamalarını kurar.
3. Hüseyin Cengiz uygulama tablolarını Frappe geçişiyle oluşturur.
4. Hüseyin Cengiz gizli anahtarları gizli bilgi deposundan sağlar.
5. Hüseyin Cengiz HTTPS adresini ve sertifika güvenini doğrular.
6. Hüseyin Cengiz uçta 16.384 baytlık giriş sınırı uygular.
7. Hüseyin Cengiz aşağıdaki gerçek istek denemelerini çalıştırır.

Giriş sınırı Frappe'den önce çalışan sunucuda uygulanmalıdır.
Örneğin Nginx için `client_max_body_size 16k` ayarı kullanılır.
Bu ayar yalnız imzalı kanalın adresine uygulanır.
Frappe, gövdeyi `before_request` kancasından önce okur.
Uygulamanın boyut denetimi bu ilk okumayı sınırlamaz.
QA, uzunluğu bilinmeyen isteklerde de sunucu sınırını doğrular.

Gönderen site ayarları şunlardır:

| Alan | İşlev |
| --- | --- |
| `press_job_status_endpoint` | Alıcının tam HTTPS adresini tutar. |
| `press_job_status_key_id` | Gönderenin anahtar kimliğini tutar. |
| `press_job_status_key` | Gönderenin gizli anahtarını tutar. |

Alıcıdaki `press_job_status_keys` alanı anahtar kimliklerini anahtarlarla eşler.
Anahtar yenilenirken eski ve yeni anahtar birlikte bulunabilir.
Anahtar değeri Git'e, rapora veya günlüğe yazılmaz.

Müşteri Press Webhook adresi için HTTPS zorunludur.
Yerel istisna için `deployment_environment=local` ve `developer_mode=1` gerekir.
Bu durumda yalnız localhost ve yerel IP adresi HTTP kullanabilir.
Bu istisna ajan kanalını kapsamaz.

## Gerçek ortamda yapılacak denemeler

QA aşağıdaki denemeleri ayrı ortamda yapar.
Bu denemeler henüz yapılmadı.

1. QA Press durum değişikliğini gerçek panel bağlantısından izler.
2. QA aynı olayı iki eşzamanlı istekle yollar.
3. QA gelen kutusunda tek kayıt kaldığını doğrular.
4. QA imzasız ve bozuk imzalı isteklerin 401 aldığını doğrular.
5. QA bilinmeyen anahtarı ve eski zaman damgasını dener.
6. QA reddedilen isteklerin gelen kutusuna yazılmadığını doğrular.
7. QA kaynak işlem geri alınınca olayın da silindiğini doğrular.
8. QA iki hızlı kayıt geçişinin iki olay oluşturduğunu doğrular.
9. QA doğrudan yazılan son durumun uzlaştırıcıyla geldiğini doğrular.
10. QA başarısız gönderimin aynı kimlikle yeniden denendiğini doğrular.
11. QA ajan imzasıyla müşteri bildirim ayarını değiştirmeyi dener.
12. QA müşteri yetkisi olmadan bu işlemin reddedildiğini doğrular.
13. QA başka takımın müşteri bildirim kaydına erişmeyi dener.
14. QA rc ve prod ayarlarında HTTP adresini dener.
15. QA bu adreslerin kayıt sırasında reddedildiğini doğrular.
16. QA bozuk `application/json` isteğinin Frappe davranışını ayrıca kaydeder.
17. QA eşzamanlı kayıt yazılarında gerçek veritabanı kilitlerini doğrular.
18. QA etkin Site sayısını artırarak kuyruk süresini ölçer.

Uzlaştırıcı etkin kayıtları aynı koşuda okur.
Site kayıtları arşivlenene kadar etkin kalır.
Bu yüzden büyüyen kayıt sayısının etkisi ölçülmelidir.
Yerel taklit testleri gerçek veritabanı yarışını kanıtlamaz.

QA, tablo geçişini ve geri dönüş yolunu da doğrular.
Geri dönüşte mevcut olay kayıtları silinmez.
Sunucu doğrulanmadan G-15 tamamlandı sayılmaz.

## Yerel kanıt ve sürüm sınırı

Kaynaklar 24 Kasım 2026 Salı günü salt okunur incelendi.
Çalışan servisler yeniden başlatılmadı.
Press kaynağı Frappe 16.50.0 ortamında incelendi.
Kiracı kaynağı Frappe 16.56.0 ortamında incelendi.
Yerel Python sürümü 3.14.10 olarak gözlendi.

`press_tr` bildirimi Python 3.14 veya üstünü ister.
Bu uygulamanın Frappe aralığı 16.0.0 dahil, 17.0.0 hariçtir.
`platform_core` bildirimi Python 3.14 serisini ister.
Bu uygulamanın Frappe aralığı 16.56.0 dahil, 17.0.0 hariçtir.
Kilit dosyası sürümü bu gözlemlerden ayrı değerlendirilir.
Bu iş yeni paket eklemedi.

Frappe 16.56.0 `app.py` dosyasında gövde 214. satırda çözülür.
`before_request` kancaları 219. satırdan itibaren çağrılır.
Aynı dosyanın 121. satırı `cmd` yönlendirmesini seçer.
Bu sıra, ham içerik türü kararının gerekçesidir.

## Doğrulama kaydı

Korunan ilk imza testi başarıyla tamamlandı.
Yeni imza sözleşmesi önce 11 testte 24 hata verdi.
Düzeltmeden sonra 13 imza testi geçti.

Alıcının ilk 9 testi eksik kod nedeniyle 22 hata verdi.
İlk 12 olay testi eksik kod nedeniyle 26 hata verdi.
İlk 10 bağlantı testi eksik kod nedeniyle 13 hata verdi.
Bu üç koşuda hata `NotImplementedError` oldu.

Yeni kanca, alıcı ve inceleme testleri de önce başarısız koştu.
Son koşuda 64 hedefli test geçti.
Dağılım 13 imza, 10 alıcı ve 12 olay testidir.
Ayrıca 20 bağlantı ve 9 uç testi geçti.
Ruff 0.14.10 biçim ve kod denetimleri geçti.
Test kilidi başka görevdeyken test başlatılmadı.

Bağımsız inceleme ara durum kaybını ve kanca hatasının yayılmasını buldu.
İnceleme geri çağrı sırasını ve kilit sırasını da denetledi.
Bu kusurlar düzeltildi. Regresyon testleri geçti.
Bu testler düzeltilen hatanın yeniden oluşmasını denetler.

Zorunlu dal kontrolleri sırayla çalıştırıldı.
Her koşuda ortak test kilidi alındı ve bırakıldı.

| Komut | Sonuç |
| --- | --- |
| `backend/dev/bin/module-boundaries` | `pass`. İhlal bulunmadı. |
| `UV_OFFLINE=1 backend/dev/bin/security-audit` | `pass`. Mevcut JSON istisna listelerine kayıt eklenmedi. |
| `backend/dev/bin/ai-readiness` | `pass`. Aşağıdaki iki çekirdek kontrolü çalışmadı. |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/tests` | `pass`. 103 test tamamlandı. İki test atlandı. |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/naming/tests` | `pass`. 68 test geçti. |

Görev testleri aşağıdaki komutlarla çalıştırıldı:

```sh
~/.local/bin/python3.14 -B -m unittest discover -s apps/press_tr/tests -p test_job_status_signing.py
~/.local/bin/python3.14 -B -m unittest discover -s apps/press_tr/tests -p test_job_status_events.py
~/.local/bin/python3.14 -B -m unittest discover -s apps/press_tr/tests -p test_job_status_runtime.py
~/.local/bin/python3.14 -B -m unittest discover -s apps/platform_core/platform_core/ai -p test_press_events.py
~/.local/bin/python3.14 -B -m unittest discover -s apps/platform_core/platform_core/api -p test_press_status.py
```

İlk güvenlik koşusu testlerdeki `_` değişken adını reddetti.
Proje bu adı çeviri işlevine ayırır.
Değişkenler düzeltildi. Etkilenen kontroller tekrar çalıştırıldı ve geçti.
Yeni tablo adları uygulamaların terim sözlüklerine eklendi.

İki eski Semgrep kapsamının gerekçeleri bağımsız incelemede korundu.
Semgrep, kaynak kodundaki güvenlik kurallarını denetleyen araçtır.
Yalnız bu kapsamların dosya özetleri yenilendi.
İstisna listeleri ve tarama kuralları değişmedi.
Yeni kodda dört dar satır içi istisna bulunur.
Bu istisnaların her biri kod içinde gerekçelendirildi.
Bağımsız inceleme bu gerekçeleri de denetledi.

`translation_core` ve `dependency_core` kontrolleri `not_run` durumundadır.
İlki için Frappe çekirdek çeviri kataloğu bulunmadı.
İkincisi için Frappe 16.56.0 paket bildirimi bulunmadı.
Genel ad ve ShellCheck uyarıları teslimi durduran hata değildi.
ShellCheck, kabuk komut dosyalarını denetleyen araçtır.

Gerçek HTTP, panel ve veritabanı denemeleri `not_run` durumundadır.
CI çalışmadı. Playwright bu görevin kapsamı dışındadır.
Bu not QA kabulü bildirmez.

## Yazım denetimi

Komutlar, dosya yolları ve ileti biçimleri aynen korundu.
Otomatik Türkçe denetimi iki Markdown dosyasında çalıştırıldı.
Denetim hata bulmadı. Uyarılar elle incelendi.
O-57 bölümündeki açıklamalar 15 kelime sınırını korur.
Önceki kararların alıntıları ve görev dışındaki metinler değiştirilmedi.
Teknik adlar ile dosya yolları doğruluk için aynen korundu.
Gerçek okurla denenmedi.

## Ana dala taşıma (AJA-2432)

Bu iş 28 Kasım 2026 Cumartesi günü ana dala taşındı.
Kaynak eski `pc/job-status-events` dalının `72d87970` commit'idir.
Dosyalar `backend/` öneki olmadan taşındı.

Ana dalla çakışan dosyalarda ana dalın kodu esas alındı:

- `platform_core/hooks.py` içinde G-40 kancası ilk sırada kaldı. Olay kancası onun arkasına eklendi.
- `press_tr/hooks.py` içinde `User` kaydının ana daldaki iki kancası korundu.
- `Site` kaydı ana daldaki `validate` kancasını korudu. `on_update` kancası yanına eklendi.
- İki `tr.csv` dosyasında iki tarafın satırları birlikte tutuldu.
- `dev/module-boundaries.json` dosyasında iki tarafın satırları birlikte tutuldu.
- `semgrep-exceptions.json` içinde iki kapsamın özeti yeniden hesaplandı. Yeni istisna eklenmedi.
- `dev/tests/test_login_method_allowlists.py` ana dalda yeni bir kapıdır. `press_status.receive` ucu orada `GUEST` olarak adlandırıldı. İmzalı gövde bu ucu yetkilendirir.

Eski dal `PROJECT-RECORD.md` dosyasına bir karar ekliyordu.
O karar eski dalda O-57 numarasını taşıyordu.
Ana dalda O-57 numarası başka bir karara verildi.
Bu yüzden karar kaydı bu taşımaya alınmadı.
Bu notta geçen O-57, eski dalın kararıdır.
Kararın yeni numarasını proje kaydının sahibi verir.

Gerçek HTTP, panel ve veritabanı denemeleri yine `not_run` durumundadır.
