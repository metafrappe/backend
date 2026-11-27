# Yapay zekâ kimliği devri

Bu not AJA-82 görevinin yerel kodunu ve kalan işlerini açıklar.
Dalın adı `pc/aja1617-ai-identity` olur. Karar O-63 içindedir.

## Yerel değişiklikler

Aracı izni artık her istekte tek hedefe göre denetlenir.
Hedef değişirse eski izin reddedilir.
Kapatılmış kullanıcıya ait izin reddedilir.
Kullanıcı kimliği kurulurken çağrının bilgileri korunur.

Press araçlarında üç kimlik biçimi vardır.
`own_user`, kullanıcının mevcut yerel aracıdır.
`service_account`, ayrı servis hesabıdır. Bu hesap yalnız operasyon listesini kullanır.
`delegated`, kullanıcıya bağlı kısa süreli Press iznidir.
Bu izin yalnız bellekte tutulur. Yenileme izni saklanmaz.

Araç, her çağrıda Press'in döndürdüğü kullanıcıyı denetler.
Onaylanan öneri, hesap adına ve tam hedef adresine bağlıdır.
Kimlik değişirse öneri yürütülmez.
Servis çağrısı, geçmiş kaydı yazılamazsa başlamaz.
Erişim bilgileri geçmişe yazılmaz.

## Kayıtların kapanış sınırı

| Kayıt | Yerel kanıt | Kalan iş |
| --- | --- | --- |
| G-27 | Servis hesabı sınırı, operasyon listesi ve onay öncesi önizleme testleri. | Ayrı gerçek hesap, ağ izin listesi ve ticari araç sunucusu gerekir. |
| G-28 | Bellekteki Press izni, süre, hedef ve kullanıcı eşleme testleri. | Press OAuth kurulumu ve gerçek kullanıcı akışı gerekir. |
| G-59 | Hedef, iptal, kullanıcı durumu ve çağrı kimliği testleri. | Müşteri onayı AJA-101 görevindedir. Gerçek HTTP testleri ayrıca koşulmalıdır. |
| G-82 | Tek hedef, kimliğe bağlı onay ve kalıcı kullanıcı anahtarı reddi. | Servis zinciri gerçek ortamda doğrulanmalıdır. |

Bu dört gereksinimin tamamı kapanmış sayılmaz.
Yerel kod, sunucu kurulumu için hazırdır.
Yalnız arayüz isteyen parça kapsam dışıdır: `atonota-web`.

## İmzalı izin ile aracı izni

`fsat_` izni imzalı JWT değildir.
JWT, imzalı alanlar taşıyan bir erişim biçimidir.
Mevcut aracı izni rastgele üretilir. Sunucu iznin özetini ve süresini saklar.
Bu dal aracı izninin biçimini değiştirmez.

İmzalı izin denetimi `backend/libs/oidc_verify/` kitaplığındadır.
Bu kitaplık imzayı, süreyi, sağlayıcıyı ve tek hedefi denetler.
MCP kullanıcı eşlemesi `identity/mcp_tokens.py` dosyasındadır.
Bu yol her istekte izin veren sunucuya iptal durumunu sorar.
Bu katmanların testleri aracı izninin testlerinden ayrı raporlanır.

## Sunucu devri

DevOps sorumlusu şu işleri hazırlık ortamında yapar:

1. Press'te ayrı bir servis hesabı açın.
2. Hesabın yalnız gereken operasyon izinlerini taşıdığını doğrulayın.
3. Servisin yalnız izin verilen ağ adreslerine ulaşmasını sağlayın.
4. Press'te kullanıcı izni veren OAuth istemcisini tanımlayın.
5. İzin süresini ve iptal davranışını gerçek Press ile doğrulayın.
6. Kullanıcı kimliğinin bütün çağrılarda korunduğunu doğrulayın.
7. AJA-101 destek onayını aynı ortamda doğrulayın.

OAuth, kullanıcının parolasını paylaşmadan sınırlı erişim vermesini sağlar.
Uygulama, erişim iznini Press'in kendi akışından almalıdır.
Keycloak oturumu tek başına bu izni sağlamaz.
Frappe, kendi OAuth iznini `Bearer` başlığıyla kabul eder.
Kaynak [Frappe kimlik belgesidir](https://docs.frappe.io/framework/user/en/guides/integration/rest_api/token_based_authentication).
Panelde izin verme akışı `atonota-web` kapsamındadır.
Ticari araç sunucusu için A Takımı PO ayrı iş açmalıdır.
Canlı ortam değişikliği bu teslimin kapsamında değildir.

Kabul için yanlış hedef ve iptal edilmiş izin reddedilmelidir.
Müşteri onayı yoksa destek erişimi reddedilmelidir.
Onaylanmamış ticari işlem hiçbir değişiklik yapmamalıdır.
Geçmişte kullanıcı, servis ve işlem sonucu birlikte bulunmalıdır.
Gizli değerler geçmişte bulunmamalıdır.

Geri dönüşte yeni kimlik kiplerini kullanan servis kapatılır.
Yerel `own_user` davranışı korunur. Bu dal veri geçişi içermez.

## Doğrulama

Denetimler `pc-ai-identity` çalışma klasöründe sırayla çalıştırıldı.
Ortak kapı kilidi bu koşularda AJA-82 görevindeydi.
İlk testler beklenen eksikleri gösterdi. Sonra kod düzeltildi.

| Komut | Yerel sonuç |
| --- | --- |
| `backend/dev/bin/module-boundaries` | `pass` |
| `UV_OFFLINE=1 backend/dev/bin/security-audit` | `pass` |
| `backend/dev/bin/ai-readiness` | `pass` |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/tests` | `pass`. 111 test koşuldu. 2 test atlandı. |
| `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/naming/tests` | `pass`. 68 test geçti. |
| `~/.local/bin/python3.14 -B -m unittest discover -s packages/press-ai/tests` | `pass`. 180 test koşuldu. 1 test atlandı. |
| `~/.local/bin/python3.14 -I packages/press-ai/server.py check-contract` | `pass`. 0 hata bulundu. |
| `uv run --no-project --offline --python 3.14 --with PyJWT==2.15.1 --with cryptography==50.0.2 python -B -m unittest discover -s backend/libs/oidc_verify/tests` | `pass`. 110 test koşuldu. 6 test atlandı. |

Son komutta `PYTHONPATH=backend/libs/oidc_verify/src` kullanıldı.
Kılavuz sırası ve site haritası denetlenmedi. Bu girdiler verilmedi.
Gerçek çalışma sürümü Python 3.14.10 olarak gözlendi.
İmza testleri PyJWT 2.15.1 ve cryptography 50.0.2 kullandı.
Frappe sürümü bu koşuda gözlenmedi.
Press paketi Python 3.9 sözdizimiyle ayrıca çözümlendi.
Gerçek Python 3.9 çalışma denemesi yapılmadı.

Yeni aracı kimlik testlerinin 9'u geçti.
Yeni Press kimlik testlerinin 17'si geçti.
İki inceleme bulgusu önce testte başarısız oldu. Düzeltmelerden sonra testler geçti.
Bağımsız inceleyici iki bulgunun kapandığını doğruladı.

Backend değişiklikleri Ruff kod ve biçim denetimlerinden geçti.
Ruff sürümü 0.17.6 olarak gözlendi.
Press dosyalarının ek Ruff taraması iki eski bulgu verdi.
Bu taramanın durumu `fail` olarak kalır.
`press_ops.py` dosyasında `F841` bulgusu vardır.
`tools.py` dosyasında `F402` bulgusu vardır.
İki bulgu da değişiklik öncesindeki kaynakta ayrıca doğrulandı.
Bu dal ilgisiz eski satırları değiştirmedi.

Türkçe denetimi üç değişen Markdown dosyasında çalıştırıldı.
Proje kaydında ve bu notta hata bulunmadı.
`INTERFACE.md` dosyasında önceden kalan 68 yazım hatası vardır.
Dosyanın önceki sürümü de aynı 68 hatayı verdi.
Yeni kimlik bölümü ayrıca denetlendi. Bu bölümde hata bulunmadı.
Uyarılar elle incelendi. Teknik adlar ve komutlar aynen korundu.
Test kaydında mevcut HTTP hata yolunun `ResourceWarning` uyarısı da vardır.

Ham komut kayıtları `.pane/scratch/ai-identity/` klasöründedir.
Gerçek Press, Keycloak ve Frappe HTTP denemeleri henüz çalıştırılmadı.
Bu denemelerin durumu `not_run` olur. CI çalıştırılmadı.
CI, depodaki otomatik denetim sürecidir.

Gerçek okurla denenmedi.
