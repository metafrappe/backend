# Dış MCP istemcisinin yerel OAuth kanıtı

Bu kayıt 23 Kasım 2026 Pazartesi günü hazırlandı. Görev AJA-57 kapsamındadır.
Kanıt yereldir. Canlı sunucu kullanılmadı.

MCP, yapay zekâ istemcisinin araç çağırdığı protokoldür.
OAuth, parolayı araç sunucusuyla paylaşmadan giriş yapılmasını sağlar.

## Sonuç

Resmî MCP Python istemcisi gerçek Keycloak üzerinden giriş yaptı.
Aynı istemci gerçek Frappe sunucusunda `plt_search_doctypes` aracını çağırdı.
Araç başarılı yanıt verdi. İmzası bozulmuş gerçek belirteç 401 ile reddedildi.
Betik bu akışı yeni girişle tekrar çalıştırdı. İkinci deneme de geçti.

Giriş kodunun değişimini hazır SDK yürüttü. SDK, hazır istemci kitaplığıdır.
Test yardımcısı yalnız örnek hesabın giriş formunu ve izin formunu doldurdu.
Parola izni akışı kullanılmadı. Playwright ve gerçek tarayıcı kullanılmadı.

Son başarılı denemenin çıktısı şöyledir:

```json
{
  "environment": "local",
  "client": "mcp",
  "client_version": "1.29.0",
  "protocol": "2025-11-25",
  "oauth": "pass",
  "authorization_requests": 1,
  "requested_scope": "mcp",
  "scope_mcp_only": true,
  "pkce_s256": true,
  "pkce_exchange": true,
  "authorization_resource": true,
  "token_resource": true,
  "tool": "plt_search_doctypes",
  "tool_call": "pass",
  "invalid_token_case": "tampered_signature",
  "invalid_token_status": 401
}
```

PKCE, giriş kodunun başka istemcide kullanılmasını önler.
Test, `code_verifier` özetini `code_challenge` değeriyle karşılaştırdı. İki değer eşleşti.
SDK yalnız bir giriş başlattı. `offline_access` kapsamı istenmedi.
Belirteçler dosyaya yazılmadı. Sonuç kaydı parola, giriş kodu veya belirteç içermez.

## Yerel ortam

- Çalışma dalı `pc/mcp-oauth-client` adındadır.
- Başlangıç `d54673d058a86b8af97f7589d3263060892461d1` commit kodudur.
- Teslim öncesinde `18a9fff8dc22368e2e5be0a2c509c0c1a552e648` backend kaydı bu dala alındı.
- Ayrı Compose projesi `fs-aja57-oauth` adındadır.
- Projede Keycloak, Frappe, MariaDB ve Redis çalıştı.
- Keycloak adresi `https://identity.localhost:7840` oldu.
- Frappe adresi `https://tenant1.localhost:7841` oldu.
- Ana bilgisayardaki iki port yalnız `127.0.0.1` adresine bağlandı.
- Dönüş adresi `http://127.0.0.1:7842/callback` olarak kaydedildi.
- İstemci dönüşü HTTP yanıtından okudu. Dönüş portunda dinleyici açılmadı.
- Sertifika denetimi açık kaldı. İstemci ve Frappe yerel sertifikaya güvendi.
- `identity.localhost` adı ayrı Compose ağında Keycloak kabına çözüldü.
- Frappe kullanıcısı uydurma bir `Website User` hesabıydı.
- Çalışan 7400 ortamında ayar değiştirilmedi. Bu ortam yeniden başlatılmadı.

Test, depodaki tam realm dosyasının ayrı kopyasını kullandı.
Realm, Keycloak içindeki hesap ve giriş ayarları grubudur.
Üç MCP istemcisi bu kopyada açıldı. `resource-indicators` özelliği etkinleştirildi.
Giriş akışları ve MCP güvenlik denetimleri korundu.
Dış kimlik sağlayıcıları, e-posta ve olay gönderimi test kopyasında kapatıldı.
Böylece örnek giriş dış servise veri göndermedi.
Keycloak bu testte H2 veritabanını kullandı. Frappe ayrı MariaDB veritabanını kullandı.
Yerel kurulum üretim ortamının birebir kopyası değildir.
Yerel realm kopyası başlangıç kaydından hazırlandı.
Son birleşmede MCP istemcileri, kapsamları ve güvenlik kuralları değişmedi.
Parolayla giriş akışı da değişmedi. Bu parçalar iki kaynakta karşılaştırıldı.
Birleşen yeni dış giriş akışları bu testin kapsamında değildir.

## Sürüm kanıtı

| Parça | Bildirilen koşul | Kilit | Gözlenen sürüm |
| --- | --- | --- | --- |
| Test istemcisi | `mcp==1.29.0` | Aynı sürüm, paket özetleriyle | 1.29.0 |
| HTTP istemcisi | MCP bağımlılığı | `httpx==0.28.1` | 0.28.1 |
| Python | Platform için `>=3.14,<3.15` | Çalıştırılabilir dosya seçildi | 3.14.10 |
| Frappe | `>=16.56.0,<17.0.0` | Mevcut yerel tenant imajı | 16.56.0 |
| Keycloak | Dockerfile içinde 26.8.2 | Mevcut yerel Keycloak imajı | 26.8.2 |

Kilit dosyası 29 paketin tam sürümünü tutar. Dosyada paket özetleri de vardır.
`uv pip sync --offline --require-hashes` komutu bu dosyayla geçti.
Yeni paketler yalnız ayrı test ortamına kuruldu. Uygulama bağımlılıkları değiştirilmedi.

## Önce başarısız olan testler

1. İlk test, uzak adresin kabul edildiğini gösterdi.
2. İnceleme testi, parolanın tekrar gönderildiğini gösterdi.
3. Diğer inceleme testi, başka realm adresinin kabul edildiğini gösterdi.
4. Gerçek giriş, izin formunda HTML kimliği bulunmadığını gösterdi.
5. Test bu gerçek form biçimiyle önce başarısız oldu.
6. Düzeltmelerden sonra 10 testin tamamı geçti.

## Dal kapıları

Komutlar çalışma dalının kökünde sırayla koşuldu. Ortak test kilidi kullanıldı.

Bu tablo eski depodaki koşuyu gösterir. O depoda yollar `backend/` ile başlıyordu.

| Sıra | Komut | Sonuç |
| --- | --- | --- |
| 1 | `backend/dev/bin/module-boundaries` | `pass` |
| 2 | `UV_OFFLINE=1 backend/dev/bin/security-audit` | `pass` |
| 3 | `backend/dev/bin/ai-readiness` | `pass` |
| 4 | `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/tests` | `pass`: 102 test, 2 atlama |
| 5 | `~/.local/bin/python3.14 -B -m unittest discover -s backend/dev/naming/tests` | `pass`: 68 test |
| 6 | Test ortamının Python komutuyla `-B -m unittest discover -s backend/e2e/mcp_oauth/tests` | `pass`: 10 test |
| 6 | [İstemci belgesindeki](../../e2e/mcp_oauth/README.md) gerçek yerel giriş komutu | `pass` |

Ruff 0.14.10 ile biçim ve kod denetimi geçti.
Geliştirme kapısındaki iki atlama, kurulu olmayan sözleşme testi paketlerinden kaynaklandı.
Atlanan dosyalar `test_gateway_openapi.py` ve `test_identity_sync_target_contracts.py` oldu.
Bu dosyalar `dev/requirements-contract-tests.txt` kurulumunu istiyor.
İstemcinin yeni testlerinde atlama yoktur.
Bağımsız inceleme AJA-134 görevinde yapıldı. Yeniden incelemede açık bulgu kalmadı.
İnceleyici dosya değiştirmedi. Testleri geliştirici çalıştırdı.

İlk güvenlik denetimi, henüz Git'e eklenmeyen istemci dosyalarını taramadı.
Dosyalar kaydedilince Bandit dört sabit değeri sır olarak işaretledi.
Bandit, Python kodunu güvenlik sorunları için tarayan araçtır.
Bağımsız inceleyici dört değerin gerçek sır olmadığını doğruladı.
İstisnalar yalnız ilgili işlemin özetine bağlandı. Tarama kuralları açık kaldı.
İstisnalar 22 Şubat 2027 Pazartesi günü sona erer.
Son güvenlik denetimi, Git'e kaydedilmiş istemci dosyalarıyla yapıldı.

Değişen üç Markdown dosyası Türkçe denetiminden geçti. Denetim hata bulmadı.
Yeni açıklamaların uzun kelime uyarıları elle incelendi. Teknik adlar aynen korundu.
Proje kaydındaki eski uyarılar bu iş kapsamında değiştirilmedi.

## Sınırlar

CI çalışmadı. CI, depodaki otomatik denetim ortamıdır.
Tarayıcı ve canlı sunucu doğrulaması `not_run` durumundadır.
Bu görev için sunucu işi kalmadı. Üretimde OAuth açılmadı.
Yeni üretim ayarı ayrı bir yetkilendirme ve dağıtım işi gerektirir.
Bu yerel kanıt, üretim kurulumu veya tam OAuth uygunluk belgesi değildir.

Gerçek okurla denenmedi.

## Yeni depoda koşu

Dosyalar 27 Kasım 2026 Cuma günü `metafrappe/backend` deposuna taşındı.
Dal `origin/main` ucundan açıldı. Uç `b94af6ac` commit'idir.
Yollardan `backend/` öneki kalktı. Karar numarası O-64 oldu.

| Sıra | Komut | Sonuç |
| --- | --- | --- |
| 1 | Test ortamının Python komutuyla `-B -m unittest discover -s e2e/mcp_oauth/tests` | `pass`: 10 test |
| 2 | Python 3.14 ile `dev/bin/module-boundaries` | `pass`: 0 ihlal |
| 3 | `dev/bin/ai-readiness` | `pass`: iki denetim `not_run` |
| 4 | `uvx ruff@0.14.10 format --check --config dev/ruff.toml e2e/mcp_oauth` | `pass` |
| 5 | Bandit 1.9.4 ile iki dosya ve istisna eşleşmesi | `pass`: 4 bulgu, 4 eşleşme |

Ruff kod denetimi iki içe aktarma sırası uyarısı verdi. Eski dalda da aynı uyarılar vardı.
Taşıma kodu değiştirmedi. Bu yüzden uyarılar ayrı bir işte düzeltilebilir.
`dev/bin/security-audit` bu ana dalda koşulmadı. Betik hâlâ `backend/` önekli yolları arıyor.
Bandit istisna eşleşmesi bu yüzden tarayıcının imza işleviyle ayrıca denendi.
Canlı yerel giriş bu taşımada yeniden koşulmadı. GitHub CI iş akışı bu depoda yoktur.
