# İş anahtarı sözleşmesi ve uç listesi

Bu belge A ve B takımının ortak sözleşmesidir. Kaynak iş AJA-1749, üst iş AJA-1730'dur.

İş anahtarı bir isteğin kimliğidir. Aynı istek iki kez gelirse sunucu işi bir kez yapar. Kullanıcı tek sonuç görür.

İlgili gereksinimler G-125, SA-6, SA-8 ve SA-11'dir.

## Ne zaman geçerli

Bu sözleşme kalıcı etkisi olan her uç için geçerlidir. Örneğin plan satın alma, kredi yükleme, davet ve destek kaydı böyledir.

Şu durumlar bu sözleşmenin konusudur:

- Kullanıcı düğmeye iki kez basar.
- İkinci sekme aynı işi yeniden gönderir.
- İstek sunucuya ulaşmaz. İstemci isteği yeniden gönderir.
- Sunucu işi yapar ama yanıt yolda kaybolur.
- Eski bir yanıt yenisinden sonra gelir.
- Ödeme sağlayıcısı aynı bildirimi iki kez gönderir.

İş anahtarı dilden bağımsızdır. Arayüz dili değişse de anahtar aynı kalır.

## Eylem türleri

Uç listesindeki her uç şu yedi türden birini taşır.

| Tür | Anlamı | Tekrar edilirse |
| --- | --- | --- |
| okuma | Uç yalnız okur. | Bir şey değişmez. |
| yeni kayıt | Uç yeni bir kayıt açar. | İş anahtarı ikinci kaydı önler. |
| hedef durum | Uç kaydı belli bir duruma getirir. | Kayıt zaten o durumdaysa sonuç aynıdır. |
| artış | Uç bir sayıya ekler. Örneğin bakiyeye kredi ekler. | İş anahtarı ikinci eklemeyi önler. |
| sürümlü düzenleme | Uç var olan kaydın alanlarını değiştirir. | Sürüm koşulu eski bilgiyle yazmayı önler. |
| toplu işlem | Uç çok satırı tek istekte işler. | Her satırın ayrı anahtarı vardır. |
| uzun iş | Uç işi kuyruğa koyar ve hemen döner. | Aynı anahtar ikinci işi kuyruğa koymaz. |

## 1. Anahtarın adı ve biçimi

İstemci anahtarı `Idempotency-Key` başlığında gönderir.

Anahtar küçük harfli bir UUID 4 değeridir. UUID, rastgele üretilen 36 karakterlik bir kimliktir. Örneğin `3f2b8c1e-6d4a-4f0b-9a7e-2c5d8e1f0a3b` bir anahtardır.

Anahtar gerektiren bir uca başlık gelmeyebilir. Bu durumda sunucu 400 kodu ve `IdempotencyKeyMissingError` hatası döner. Biçim yanlışsa da aynı hata döner.

İstemci anahtarı şu kurallarla üretir:

1. İstemci anahtarı kullanıcının ilk basışında üretir.
2. İstemci anahtarı tarayıcının kalıcı deposuna yazar. Depo adı `localStorage`'dır.
3. Depodaki ad kurumu, eylemi ve formu birlikte içerir. Örneğin `idempotency-key:<team>:plan-checkout:<plan>` bir addır.
4. İkinci sekme aynı adı okur. Böylece iki sekme aynı anahtarı gönderir.
5. İstemci ağ hatasında ve zaman aşımında aynı anahtarı yeniden gönderir.
6. İstemci kesin sonuç gelince anahtarı depodan siler.
7. İstemci anahtarın yanına üretim zamanını yazar.
8. Anahtar 23 saatten eskiyse istemci isteği kendiliğinden yeniden göndermez. Önce ilgili listeyi yeniden yükler. Kullanıcı sonucu orada görür.
9. İstek sürerken düğme kapalı kalır. Düğmede `Processing` yazar. Türkçesi "İşleniyor" olur.

Anahtarın içinde kişisel bilgi olmaz. Anahtar yalnız rastgele bir değerdir.

## 2. Anahtarın kapsamı

Anahtar üç şeyle birlikte geçerlidir: kurum, hesap ve uç.

- Press'te kurum, ekiptir. Sunucu ekibi `get_current_team()` ile alır. Bu çağrı `X-Press-Team` başlığını okur ve kullanıcının o ekibin üyesi olduğunu denetler.
- Müşteri sitesinde kurum, sitenin kendisidir. Anahtar tablosu o sitenin veritabanında durur.
- Sunucu istek gövdesindeki kurum bilgisini kapsam için kullanmaz.
- Hesap, isteği gönderen kullanıcıdır.
- Uç, çağrılan yöntemin tam adıdır. Örneğin `press_tr.api.billing.start_plan_checkout` bir uçtur.

Aynı anahtar başka bir kurumda başka bir anahtar sayılır. Sunucu başka kurumun sonucunu hiçbir zaman döndürmez. Örneğin kullanıcı kurum değiştirdi. Eski kurumun anahtarı yeni kurumda eski sonucu getirmez.

Sunucu yetkiyi her istekte yeniden denetler. Bu kural tekrar istekleri için de geçerlidir. Kullanıcının yetkisi gittiyse tekrar isteği 403 kodu alır. Sunucu eski sonucu göstermez.

## 3. Saklama süresi

Sunucu anahtar kaydını 24 saat saklar. Süre iş bittiği andan başlar.

Süresi dolan anahtar bilinmeyen anahtar sayılır. Bu yüzden ödeme uçları yalnız bu kayda güvenmez. Ödeme kaydında `idempotency_key` adlı bir sütun vardır. Bu sütun kurumla birlikte tekildir ve kalıcıdır. Ayrıntı 8. ve 9. bölümdedir.

Anahtar kaydında şu alanlar vardır:

- kurum, hesap ve uç,
- anahtar,
- istek gövdesinin özeti,
- durum: `processing` ya da `done`,
- kilit bitiş zamanı,
- yanıt kodu,
- sonuç kaydının türü ve adı,
- bitiş zamanı.

İstek gövdesinin özeti SHA-256 ile hesaplanır. Sunucu önce gövdeyi sıralı anahtarlarla JSON yapar. `cmd` ve `csrf_token` alanları özete girmez.

Anahtar kaydında yanıt gövdesi saklanmaz. Sunucu yanıtı sonuç kaydından yeniden üretir. Böylece kayıtta gizli bilgi ve kişisel veri birikmez.

Kurum, hesap, uç ve anahtar birlikte tekil dizindir. Veritabanı aynı dörtlüden ikinci satırı kabul etmez.

## 4. Aynı anahtar ve aynı içerik

Sunucu işi ikinci kez yapmaz. İlk isteğin sonucunu döner.

- Yanıt kodu ilk yanıtın kodudur.
- Yanıt aynı sonuç kaydını gösterir.
- Yanıtta `Idempotent-Replayed: true` başlığı vardır.
- Yeni kayıt açılmaz. Yeni tahsilat yapılmaz. Yeni bildirim gitmez.

İlk istek hata ile bitmiş olabilir. Bu durumda sunucu anahtar kaydını siler. Tekrar isteği işi baştan yapar. Ödeme uçlarında baştan yapmanın kuralı 8. bölümdedir.

## 5. Aynı anahtar ve başka içerik

Sunucu isteği reddeder. Yanıt kodu 422, hata adı `IdempotencyKeyReusedError` olur.

Bu hata istemci hatasıdır. Kullanıcı yanlış bir şey yapmamıştır. Arayüz bu durumda bir uyarı gösterir. Uyarının metni 13. bölümdedir.

İstemci bu hatadan sonra yeni bir anahtar üretir.

## 6. İlk istek sürerken gelen istek

Sunucu anahtar kaydını işten önce yazar ve hemen kalıcı yapar. Bu, kısa ve ayrı bir veritabanı işlemidir. Veritabanı işlemi, ya hepsi ya hiçbiri kaydedilen değişiklik grubudur.

Sunucu şu sırayla çalışır:

1. Sunucu anahtar kaydını `processing` durumuyla yazar. Kilit bitiş zamanı şimdiden 120 saniye sonradır.
2. Sunucu bu kaydı hemen kalıcı yapar (`frappe.db.commit()`).
3. Sunucu işi yapar.
4. Sunucu işin son yazımıyla aynı veritabanı işleminde kaydı `done` yapar. Sonuç kaydının adını da yazar.
5. İş hata verirse sunucu anahtar kaydını siler.

İkinci istek aynı tekil dizine yazmaya çalışır. Veritabanı `frappe.DuplicateEntryError` hatası verir. Sunucu bu hatadan sonra kaydı kilitleyerek yeniden okur (`for_update=True`). Böylece veritabanının eski görüntüsünü değil, son halini okur. Sonra şu kurallar geçerlidir:

1. Kayıt `done` ve özet aynıysa sunucu 4. bölümdeki gibi ilk sonucu döner.
2. Özet farklıysa sunucu 5. bölümdeki hatayı döner.
3. Kayıt `processing` ve kilit süresi dolmadıysa sunucu 409 kodu döner. Hata adı `IdempotencyInProgressError` olur. Yanıtta `Retry-After: 2` başlığı vardır.
4. Kayıt `processing` ve kilit süresi dolduysa ilk istek yarıda kalmıştır. Sunucu kaydı tek bir güncellemeyle devralır. Güncellemenin koşulu kilit süresinin dolmuş olmasıdır. Sonra işi baştan yapar.

Veritabanı kilit beklemesi zaman aşımına düşebilir. Kilitlenme de olabilir. Sunucu bu iki durumu da `IdempotencyInProgressError` hatasına çevirir. Bu çeviri kendiliğinden olmaz. Ortak katman bunu açıkça yapar.

İstemci 409 yanıtında 2 saniye bekler. Sonra aynı anahtarla yeniden sorar. Arayüz `Processing` yazısını göstermeye devam eder.

Bildirim ve e-posta yalnız iş kalıcı olunca gider. Sunucu bunun için `frappe.db.after_commit.add(...)` kullanır. Kuyruğa konan işler için `frappe.enqueue(..., enqueue_after_commit=True)` kullanılır. Böylece geri alınan bir iş bildirim göndermez.

## 7. Sürüm koşulu

Var olan bir kaydı değiştiren uç sürüm koşulu alır.

- Alanın adı `version`'dır. İstemci bu alanı istek gövdesinde gönderir.
- Değer, kaydın `modified` alanıdır. İstemci bu değeri kaydı okurken alır.
- Sunucu kaydı kilitler. Sonra `version` değerini kaydın şimdiki `modified` değeriyle karşılaştırır.
- Değerler farklıysa sunucu hiçbir şey değiştirmez. Yanıt kodu 409, hata adı `VersionConflictError` olur.

`VersionConflictError` yeni bir sınıftır. Ortak katman bu sınıfı tanımlar. Sınıf Frappe'nin `TimestampMismatchError` sınıfından türer. Sınıfın `http_status_code` değeri 409'dur.

`hrms_tr` izin uçları bugün düz `TimestampMismatchError` hatası verir. Bu hatanın kodu 417'dir. `hrms_tr` bu uçlarda `VersionConflictError` sınıfına geçer. Geçiş bitene kadar istemci iki hata adını da çakışma sayar.

Kullanıcı şunu görür:

1. Arayüz bir uyarı gösterir. Uyarı, kaydın başkası tarafından değiştiğini söyler. Uyarının metni 13. bölümdedir.
2. Arayüz kaydın son halini yükler.
3. Arayüz kullanıcının yazdıklarını silmez. Kullanıcının yazdıkları formda kalır.
4. Kullanıcı farkı görür ve yeniden kaydeder.

Eski yanıt geç gelebilir. İstemci her yanıtta gelen `modified` değerine bakar. Ekrandaki değerden eski bir yanıtı ekrana yazmaz.

## 8. Sağlayıcı bildirimi: iyzico

Bu bölüm G-125 ve SA-6'ya dayanır. Testler yalnız sahte sunucu ya da iyzico sandbox ortamında koşar. Sandbox, gerçek para kullanmayan deneme ortamıdır.

iyzico üç kimlik kullanır.

| Kimlik | Kim üretir | Ne işe yarar |
| --- | --- | --- |
| `conversationId` | Bizim sunucumuz | Ödeme kaydımızın adıdır. Bir ödeme isteği bir kayıttır. |
| `token` | iyzico | Ödeme formunun kimliğidir. Bir ödeme kaydının bir `token` değeri olur. |
| `iyziReferenceCode` | iyzico | Bildirimin kimliğidir. Aynı bildirim aynı kodla gelir. |

Akış şöyledir:

1. Kullanıcı ödeme düğmesine basar. İstemci `Idempotency-Key` gönderir.
2. Sunucu bir "Iyzico Payment Record" açar. Kaydın adı `conversationId` olur. Anahtar kaydın `idempotency_key` sütununa girer.
3. Sunucu ödeme kaydını iyzico'yu çağırmadan önce kalıcı yapar. Dış çağrı açık bir veritabanı işleminin içinde yapılmaz.
4. Sunucu iyzico'dan formu ister. Gelen `token` değerini aynı kayda yazar.
5. Aynı anahtarla ikinci istek gelebilir. Sunucu ödeme kaydını `idempotency_key` ile bulur. Yeni kayıt açmaz.
6. Kayıtta `token` varsa sunucu aynı formu döner.
7. Kayıtta `token` yoksa ilk çağrının yanıtı kaybolmuştur. Sunucu formu aynı `conversationId` ile yeniden ister.
8. iyzico bildirimi gönderir. Sunucu önce imzayı denetler.
9. Sunucu bildirimi "Iyzico Webhook Log" kaydına yazar. `iyziReferenceCode` bu kayıtta tekildir. Kayıtta `processed` adlı bir alan vardır.
10. Aynı `iyziReferenceCode` ikinci kez gelebilir. Kayıt `processed` ise sunucu 200 kodu döner ve işi yinelemez. Kayıt `processed` değilse sunucu işi yeniden dener.
11. Sunucu ödeme kaydını `token` ile bulur. `conversationId` uyuşmazsa bildirimi reddeder.
12. Sunucu ödemenin durumunu iyzico'dan kendisi sorar.
13. Sunucu ödeme kaydını kilitler. Kayıt zaten "SUCCESS" ise başka bir şey yapmaz.
14. Durum "SUCCESS" ise sunucu tek geçişi yapar. Krediyi ekler ve ödenmiş faturayı açar.
15. Sunucu `processed` alanını geçişle aynı veritabanı işleminde işaretler. Geçiş hata verirse bildirim işlenmemiş kalır.

Kullanıcının dönüş adresi ve iyzico bildirimi aynı anda gelebilir. İkisi de aynı geçiş kodunu çağırır. Kayıt kilidi geçişi bir kez yaptırır.

Yanıt kaybolabilir ya da iş sonucu gelmeyebilir. Bu durumda mutabakat işi ödemeyi iyzico'dan sorar. Mutabakat, iki taraftaki kaydı karşılaştırıp eşitlemektir. Mutabakat da aynı geçiş kodunu kullanır.

7. adımda iyzico ikinci bir form açabilir. Kullanıcı ilk formu hiç görmediği için iki ödeme beklenmez. Yine de aynı `conversationId` için ikinci başarılı ödeme gelebilir. Bu durumda sunucu ikinci ödemeyi geçişe almaz. G-125'teki telafi çalışır: iade ve destek kaydı.

Ödeme alınır ama kurulum başarısız olabilir. Bu durumda G-125'teki telafi adımları çalışır. Aynı uygulama için ikinci etkinleştirme reddedilir.

SA-11 gereği fatura alanları geçişte bir kez yazılır. Bu alanlar `transaction_amount`, `transaction_net`, `transaction_fee`, `exchange_rate` ve `amount_paid` alanlarıdır. Tekrar bildirimi bu alanları yeniden yazmaz.

## 9. Banka havalesi

Bu bölüm SA-8'e dayanır.

Operatör havaleyi `press_tr.api.ops.record_bank_transfer` ile kaydeder. Bu uçta tekillik anahtarı banka referansıdır.

- Uç bu iş için `bank_account` alanını da alır. Bu alan paranın geldiği banka hesabımızdır. SA-8'deki imzaya bu alan eklenir.
- Sunucu referansın baştaki ve sondaki boşluğunu siler. Harfleri büyük harfe çevirir.
- Banka hesabı ve referans birlikte tekildir. Tekil dizin veritabanında durur. İki ayrı banka aynı referansı üretebilir. Bu yüzden referans tek başına tekil değildir.
- Aynı hesap ve referans tekrar gelebilir. Kurum, tutar ve para birimi aynıysa sunucu ilk kaydı döner. Bakiye ikinci kez artmaz.
- Bu üç bilgiden biri farklı olabilir. Bu durumda sunucu 422 kodu ve `BankReferenceConflictError` hatası döner.
- Operatör bu hatada dekontu yeniden inceler.

Bu uçta `Idempotency-Key` başlığı ayrıca gerekmez. Banka referansı bu işi görür.

## 10. Uç listesi

Tablodaki sütunların anlamı şöyledir:

- "Tür" sütunu yedi türden birini yazar.
- "Ödeme" sütunu ucun para hareketi yapıp yapmadığını yazar.
- "İş anahtarı" sütunu tekillik anahtarının gerekip gerekmediğini yazar. Sağlayıcı ve banka uçlarında anahtar 8. ve 9. bölümdeki kimliktir.
- "Sürüm koşulu" sütunu `version` alanının gerekip gerekmediğini yazar.
- "Durum" sütunu ucun depoda olup olmadığını yazar. "var" uç bugün çalışan kodda vardır demektir. Bu kod Press ya da bizim uygulamalarımız olabilir. "planlanan" uç henüz yazılmadı demektir.

Planlanan uçların adları öneridir. Uygulayan ekip adı değiştirirse bu tabloyu da aynı commit'te değiştirir.

| Kullanıcı işi | Uç | Tür | Ödeme | İş anahtarı | Sürüm koşulu | Durum |
| --- | --- | --- | --- | --- | --- | --- |
| Plan satın alma: planları görme | `press.api.site.get_plans` | okuma | hayır | gerekmez | gerekmez | var |
| Plan satın alma: ödemeyi başlatma | `press_tr.api.billing.start_plan_checkout` | yeni kayıt | evet | gerekir | gerekmez | planlanan |
| Plan satın alma: ödeme durumunu görme | `press_tr.api.billing.get_checkout_status` | okuma | hayır | gerekmez | gerekmez | planlanan |
| Plan satın alma: kurulumu yeniden deneme | `press_tr.api.billing.retry_installation` | uzun iş | hayır | gerekir | gerekmez | planlanan |
| Plan satın alma: planı değiştirme | `press.api.site.change_plan` | hedef durum | hayır | gerekmez | gerekmez | var |
| Kredi yükleme: kartla yükleme | `press_tr.api.billing.create_iyzico_checkout_form` | yeni kayıt | evet | gerekir | gerekmez | planlanan |
| Kredi yükleme: iyzico bildirimi | `press_tr.api.billing.iyzico_webhook` | hedef durum | evet | gerekir | gerekmez | planlanan |
| Kredi yükleme: havale kaydı | `press_tr.api.ops.record_bank_transfer` | artış | evet | gerekir | gerekmez | planlanan |
| Kullanıcı daveti: davet gönderme | `press_tr.api.team.invite` | yeni kayıt | hayır | gerekir | gerekmez | planlanan |
| Kullanıcı daveti: daveti geri alma | `press_tr.api.team.cancel_invitation` | hedef durum | hayır | gerekmez | gerekmez | planlanan |
| Kullanıcı daveti: üyeyi çıkarma | `press_tr.api.identity.remove_team_member` | hedef durum | hayır | gerekmez | gerekmez | var |
| Destek kaydı: kayıt açma | `platform_core.api.support.create_ticket` | yeni kayıt | hayır | gerekir | gerekmez | planlanan |
| Destek kaydı: yanıt yazma | `platform_core.api.support.add_reply` | yeni kayıt | hayır | gerekir | gerekmez | planlanan |
| Destek kaydı: dosya parçası yükleme | `platform_core.api.support.upload_attachment_chunk` | yeni kayıt | hayır | gerekir | gerekmez | planlanan |
| Destek kaydı: kaydı düzenleme | `platform_core.api.support.update_ticket` | sürümlü düzenleme | hayır | gerekmez | gerekir | planlanan |
| Destek kaydı: kayıtları görme | `platform_core.api.support.list_tickets` | okuma | hayır | gerekmez | gerekmez | planlanan |
| Toplu işlem: satırları içe alma | `platform_core.api.bulk.start_import` | toplu işlem | hayır | gerekir | gerekmez | planlanan |
| Toplu işlem: hatalı satırları yeniden deneme | `platform_core.api.bulk.retry_failed_rows` | toplu işlem | hayır | gerekir | gerekmez | planlanan |
| İzin: izni onaylama | `hrms_tr.api.approve_leave` | hedef durum | hayır | gerekmez | gerekir | var |
| İzin: izni geri çevirme | `hrms_tr.api.reject_leave` | hedef durum | hayır | gerekmez | gerekir | var |

İzin uçları hedef durum türündedir. Yine de sürüm koşulu alırlar. Kullanıcı eski bilgiyle karar vermemelidir.

## 11. Toplu işlem ve dosya parçası

Toplu işlemde her satırın kendi anahtarı vardır. Satır anahtarı, işin anahtarı ile satır numarasından oluşur.

Örnek şöyledir. 100 satırlık bir işte 3 satır hata verdi. Sunucu 97 satırın sonucunu saklar. Yeniden deneme yalnız 3 hatalı satırı işler. 97 sonuç değişmez.

Dosya parçasında anahtar üç bilgiden oluşur: dosyanın anahtarı, parçanın sırası ve parçanın SHA-256 özeti. Aynı parça iki kez gelirse sunucu bir kez yazar. Parçalar birleşince tek bir ek oluşur.

## 12. Uzun iş

Uzun iş ucu işi kuyruğa koyar. Sunucu 202 kodu ve işin adını döner.

İşin adı anahtardan türer. Sunucu adı kurum, hesap, uç ve anahtardan SHA-256 ile üretir. Ad anahtar kaydına da yazılır.

Sunucu `frappe.enqueue` çağrısında `job_id` ve `deduplicate=True` kullanır. Bu ayar yalnız iş kuyrukta beklerken ya da çalışırken ikinci işi önler. İş bittikten sonra aynı ad yeniden kuyruğa girebilir. Bu yüzden asıl koruma anahtar kaydıdır.

Tekrar isteğinde sunucu 202 yanıtını anahtar kaydından üretir. `frappe.enqueue` çağrısının dönüş değerine bakmaz. Bu çağrı işi atladığında `None` döner.

İstemci işin durumunu bir okuma ucuyla sorar.

## 13. Hata özeti

Kullanıcıya görünen metnin kaynağı İngilizcedir. Türkçesi çeviri dosyasına girer.

| Durum | Kod | Hata adı | Kaynak metin | Türkçesi |
| --- | --- | --- | --- | --- |
| Anahtar yok ya da biçimi yanlış | 400 | `IdempotencyKeyMissingError` | `Something went wrong. Reload the page.` | "Bir sorun oldu. Sayfayı yenileyin." |
| Aynı anahtar, aynı içerik | ilk kod | yok | İlk sonuç gösterilir. | İlk sonuç gösterilir. |
| Aynı anahtar, başka içerik | 422 | `IdempotencyKeyReusedError` | `This action was sent with different details. Reload the page and try again.` | "Bu işlem başka bilgilerle gönderilmiş. Sayfayı yenileyin ve yeniden deneyin." |
| İlk istek sürüyor | 409 | `IdempotencyInProgressError` | `Processing` | "İşleniyor" |
| Kayıt başkası tarafından değişti | 409 | `VersionConflictError` | `This record changed after you opened it.` | "Bu kayıt siz açtıktan sonra değişti." |
| Banka referansı başka işte kullanıldı | 422 | `BankReferenceConflictError` | `This bank reference is already used.` | "Bu banka referansı zaten kullanılmış." |

Bu uçlar `/api/method/` yoluyla çağrılır. İstemci hatayı yanıttaki `exc_type` alanından tanır. Frappe bu alanı bu yolun hata yanıtına koyar. `/api/v2/` yolunda alanın adı `errors[].type` olur. Bir uç `/api/v2/` yoluna geçerse istemci o alanı okur.

## 14. Kanıt

Testler şu sayıları ve durumu denetler:

- Açılan kayıt sayısı. Örneğin iki basışta tek sipariş açılır.
- Tahsilat sayısı. Örneğin iki bildirimde tek tahsilat olur.
- Gönderilen bildirim sayısı. Örneğin iki davet isteğinde tek e-posta gider.
- İşin son durumu. Örneğin ödeme kaydı "SUCCESS" olur ve kurulum "etkin" olur.

Bu belgeyi `contracts/tests/test_idempotency_contract.py` testi denetler. Test uç tablosunun kurallarını da denetler.
