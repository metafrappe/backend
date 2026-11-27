# Yerel MCP OAuth istemcisi

Bu betik yalnız yerel test ortamına bağlanır. Çalışan ortamı yeniden başlatmaz.
MCP, yapay zekâ istemcisinin araç çağırdığı protokoldür.
OAuth, parolayı araç sunucusuyla paylaşmadan giriş yapılmasını sağlar.

İstemci resmî MCP Python SDK 1.29.0 sürümünü kullanır.
SDK, MCP istemcisi geliştirmek için hazır bir kitaplıktır.
SDK keşfi, giriş kodunu, PKCE denetimini ve araç çağrısını yürütür.
PKCE, ele geçirilen giriş kodunun başka istemcide kullanılmasını önler.
Akış `2025-11-25` MCP sürümünü kullanır. Sunucu bu sürümü destekler.
Seçimin gerekçesi proje kaydındaki O-64 kararıdır.

## Önkoşullar

HTTPS, web bağlantısını şifreler.
Realm, Keycloak içinde hesapları ve giriş ayarlarını birlikte tutar.

- Python 3.14 gerekir. Çalışan sürüm yerelde 3.14.10 olarak gözlendi.
- Ayrı test ortamında gerçek Frappe ve Keycloak çalışmalıdır.
- HTTPS sertifikasının yetkili kökü istemciye verilmelidir. Sertifika denetimi kapatılmaz.
- Kaynak adresi `tenant1.localhost`, `identity.localhost` veya doğrudan yerel adres kullanmalıdır.
- Bütün adresler yalnız bu bilgisayara çözülmelidir.
- Örnek hesabın adı `mcp-e2e-` ile başlamalıdır. Ad `@example.test` ile bitmelidir.
- Örnek hesap etkin olmalıdır. Frappe kimlik bağı aynı Keycloak hesabını göstermelidir.
- Hesap ikinci doğrulama istememelidir. Betik ikinci doğrulamayı atlatmaz.

Keycloak, `resource-indicators` özelliğiyle başlamalıdır.
Tam realm dosyasındaki üç MCP istemcisi yalnız test kopyasında açılır.
Bu istemciler `mcp-external`, `mcp-resource` ve tam MCP adresidir.
Giriş ve belirteç istekleri aynı `resource` değerini kullanır.
Sunucu `aud` ve `mcp_resource` alanlarını bu değerle karşılaştırır.
Keycloak dönüş adresi `http://127.0.0.1:7842/callback` olarak tam kaydedilir.
Betik dönüşü HTTP yanıtından okur. Bu portta dinleyici açmaz.

Ayrı test ortamı bu önkoşulları kendisi kurar. Kurulum aşağıdaki bölümdedir.

Frappe site ayarlarında şu alanlar gerekir:

```json
{
  "mcp_oauth_enabled": 1,
  "mcp_oauth_resource": "https://tenant1.localhost:7841/api/method/platform_core.api.ai.mcp",
  "mcp_oauth_client_ids": ["mcp-external"],
  "keycloak_public_url": "https://identity.localhost:7840",
  "keycloak_internal_url": "https://identity.localhost:7840",
  "keycloak_realm": "platform"
}
```

`mcp_oauth_introspection_secret` ayrıca güvenli ayarla verilir. Gerçek değer belgeye yazılmaz.
Ayrı test ortamında bu değeri `fixture.py` betiği üretir ve yazar.
Bu değer, tam kaynak adresiyle kayıtlı Keycloak istemcisinin sırrıdır.
Frappe, Keycloak sertifikasına da güvenmelidir.
Ayrı Compose ağında `identity.localhost` adı Keycloak kabının ağ takma adıdır.
Bu ad Frappe kabına değil, Keycloak kabına çözülür.
7400 ortamındaki ayarları değiştirmeyin. Bu ortamı yeniden başlatmayın.

## Ayrı test ortamını kurun

Ayrı test ortamını `e2e/mcp_oauth/fixture.py` betiği kurar.
Betik bu ortamı kendi Compose projesinde açar. Projenin adı `fs-mcp-oauth` olur.
Compose, birden çok kabı tek proje olarak yönetir.
Betik 7400 yığınını açmaz, kapatmaz ve yeniden başlatmaz.
Betik Colima'yı da yeniden başlatmaz. İmaj indirmez ve imaj derlemez.

Komutları bu deponun kök klasöründe sırayla çalıştırın.

### 1. Değişkenleri verin

Aşağıdaki değerleri kendi işinize göre verin.

```bash
export MCP_TEST_VENV="$HOME/.cache/frappesetup/mcp-oauth-venv"
export MCP_LOCK_OWNER=AJA-1658
```

`MCP_TEST_VENV`, Python sanal ortamının klasörüdür.
Sanal ortam, Python paketlerini ayrı tutan klasördür.
Bu klasör deponun dışında olmalıdır.
`MCP_LOCK_OWNER`, kendi görev numaranızdır. Örneğin `AJA-1658` yazın.

### 2. Sanal ortamı kurun

Python 3.14 ve `uv` aracı gerekir.

```bash
uv venv --python ~/.local/bin/python3.14 "$MCP_TEST_VENV"
uv pip sync --require-hashes --python "$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/requirements.lock.txt
```

### 3. Ortamın dosyalarını hazırlayın

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/fixture.py prepare
```

Bu komut yalnız bir kez çalışır. Var olan sırları hiçbir zaman ezmez.
Komut bütün dosyaları `~/.cache/frappesetup/mcp-oauth-fixture` klasörüne yazar.
Bu klasörün adı aşağıda "ortam klasörü" diye geçer.
Ortam klasörü deponun dışındadır. Betik deponun içindeki klasörü reddeder.
Komut şu dosyaları üretir:

- `fixture.json` dosyası örnek hesabın parolasını ve öteki sırları tutar.
- `local.crt` dosyası yerel test sertifikasıdır. `local.key` dosyası onun anahtarıdır.
- `platform-realm.json` dosyası depodaki realm dosyasının test kopyasıdır.
- `compose.json` dosyası ayrı test ortamının Compose tanımıdır.

Komut gizli dosyaları yalnız sizin okuyacağınız biçimde yazar. Bu izin 0600'dır.
Komut sırları ekrana yazmaz.

Realm kopyasında şu ayarlar yapılır:

- Üç MCP istemcisi açılır.
- Örnek hesap `mcp-e2e-reader@example.test` adıyla eklenir.
- Örnek hesap etkindir ve ikinci doğrulama istemez.
- Dış kimlik sağlayıcıları, e-posta ve olay gönderimi kapanır.

### 4. Ortamı açın

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/fixture.py up
```

Bu komut ilk açılışta yaklaşık 5 dakika sürer. Komut şu işleri sırayla yapar:

1. Ortak test kilidini alır.
2. Bu projenin kapları zaten çalışıyorsa hiçbir şey yapmadan durur.
3. 7840 ya da 7841 portu doluysa hiçbir şey yapmadan durur.
4. Keycloak, Frappe, MariaDB ve Redis kaplarını oluşturur.
5. Sertifikayı ve realm kopyasını kaplara kopyalar.
6. Bu daldaki `apps/platform_core` kodunu Frappe kabına kopyalar.
7. `tenant1.localhost` sitesini kurar. Site zaten varsa veritabanını günceller.
8. Site ayarlarını yazar. `mcp_oauth_introspection_secret` değeri de bu ayarlara girer.
9. Örnek hesabın Frappe kimlik bağını kurar.
10. Keycloak ve Frappe gerçek yanıt verene kadar bekler.

Komut başarılı olunca son satırda `fs-mcp-oauth is ready` yazar.

Kurulum yarıda kalabilir. Bu durumda önce `down` komutunu, sonra `up` komutunu çalıştırın.
Veri birimleri korunur. Bu yüzden ikinci açılış daha kısa sürer.

### Kullanılan imajlar

Betik var olan yerel imajları kullanır. İmaj yoksa betik hata verir.
Varsayılan imajlar şunlardır:

- Frappe için `fs-tenant-dev:fs-e2e-7400-d048900ff39946fe9a1d` imajı kullanılır.
- Keycloak için `fs-keycloak-atonota:dev-fs-e2e-7400-d048900ff39946fe9a1d` imajı kullanılır.

Başka bir imaj kullanacaksanız `prepare` komutundan önce iki değişkeni verin.
Değişkenlerin adı `MCP_FIXTURE_TENANT_IMAGE` ve `MCP_FIXTURE_KEYCLOAK_IMAGE` şeklindedir.

### Portlar ve ağ

Ortam şu adresleri kullanır. Portlar yalnız `127.0.0.1` adresine bağlanır.

| Servis | Adres |
| --- | --- |
| Keycloak | `https://identity.localhost:7840` |
| Frappe | `https://tenant1.localhost:7841` |
| Dönüş adresi | `http://127.0.0.1:7842/callback` |

7840 portu doluysa `prepare` komutundan önce `MCP_FIXTURE_PORT` değişkenini verin.
Örneğin `MCP_FIXTURE_PORT=7850` yazarsanız portlar 7850, 7851 ve 7852 olur.

Bu Mac'te Docker'ın hazır ağ adresleri doldu.
Bu yüzden ortam `10.217.58.0/24` ağını kullanır.
Bu ağ başka bir projede kullanılıyorsa `MCP_FIXTURE_SUBNET` değişkenini verin.

Colima portları bu Mac'e taşımıyorsa betik ayrı bir SSH bağlantısı açar.
Bu bağlantı yalnız bu ortamın iki portunu taşır. `down` komutu bağlantıyı kapatır.

## Parolayı alın

Örnek hesabın parolası ortam klasöründeki `fixture.json` dosyasındadır.
Parolanın anahtarı `password` adındadır.
Dosyanın tam yolunu şu komut yazar:

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/fixture.py password-file
```

Bu komut yalnız dosya yolunu yazar. Parolayı ekrana yazmaz.
`run` komutu parolayı bu dosyadan kendisi okur. Parolayı elle vermeniz gerekmez.
Parolayı komuta, Git'e veya görev yorumuna yazmayın.

`mcp_oauth_introspection_secret` değeri de aynı dosyadadır.
Bu değerin anahtarı `introspection_secret` adındadır.
`up` komutu bu değeri Keycloak'a ve Frappe site ayarlarına kendisi yazar.

## Gerçek girişi deneyin

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/fixture.py run
```

Bu komut ortak test kilidini alır. Sonra `client.py` betiğini doğru değerlerle çalıştırır.
Parolayı `MCP_TEST_PASSWORD` değişkeniyle betiğe verir.
Yerel sertifikanın yolunu `--ca-file` ile verir.

Başarılı sonuçta üç değer şöyle olmalıdır:

- `oauth` değeri `pass` olmalıdır.
- `tool_call` değeri `pass` olmalıdır.
- `invalid_token_status` değeri `401` olmalıdır.

Betik giriş formunu örnek hesapla doldurur. Ardından erişim iznini onaylar.
Bu işlem parola izni akışı değildir. SDK giriş kodunu PKCE ile değiştirir.
SDK sonra `plt_search_doctypes` aracını çağırır.
Betik geçersiz belirteçle aynı aracı çağırır. Sunucu 401 döndürmelidir.
Betik bu deneme için gerçek belirtecin imzasını bozar.
Betik yalnız sonuç özetini yazar. Parola, kod, belirteç ve araç verisi yazılmaz.
Her çalışma yeni giriş yapar. Belirteçler yalnız bellekte tutulur.
Yanlış parola tekrar gönderilmez. Bütün akışın bekleme sınırı 120 saniyedir.
MCP yanıtının bekleme sınırı 20 saniyedir.

`client.py` betiğini elle de çalıştırabilirsiniz. Değerler `fixture.json` dosyasındadır.

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/client.py \
  --resource https://tenant1.localhost:7841/api/method/platform_core.api.ai.mcp \
  --issuer https://identity.localhost:7840/realms/platform \
  --callback http://127.0.0.1:7842/callback \
  --username mcp-e2e-reader@example.test \
  --ca-file "$HOME/.cache/frappesetup/mcp-oauth-fixture/local.crt"
```

Elle çalıştırırsanız parolayı `MCP_TEST_PASSWORD` değişkeniyle verin.

[Yerel kanıt kaydı](../../docs/evidence/mcp-oauth-client.md) sürümleri ve sonuçları gösterir.

## Birim testlerini çalıştırın

Birim testleri canlı servis kullanmaz.

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/fixture.py test
```

## Test kilidi

Aynı anda yalnız bir kişi bu ortamı kullanabilir.
Bu yüzden `up`, `run`, `test` ve `down` komutları ortak test kilidini alır.
Kilit dosyası `~/.cache/frappesetup/mcp-oauth.lock` yoludur.
Komut bitince kilit kendiliğinden bırakılır.

Kilit başkasındaysa komut hiçbir şey yapmaz.
Komut kilidin sahibini yazar ve durur. Örneğin `AJA-1653` yazabilir.
Bu durumda kilit sahibinin işini bitirmesini bekleyin.

Başka bir komutu kilitle çalıştırmak için `lock` komutunu kullanın.

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/fixture.py lock -- KOMUT
```

## Ortamı kapatın

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/fixture.py down
```

Bu komut yalnız `fs-mcp-oauth` projesinin kaplarını kaldırır.
Veri birimleri ve ortam klasörü korunur. SSH bağlantısı kapanır.
Ortamın durumunu `status` komutu gösterir.

## Sınırlar

Bu kanıt yereldir. Canlı sunucu kullanılmaz.
Betik genel bir OAuth istemcisi veya tarayıcı değildir.
Betik yalnız test hesabının parola ve izin ekranlarını işler.
İkinci doğrulama ve gerçek kullanıcı ekranları bu testin kapsamı dışındadır.
Playwright testi çalıştırılmaz. Yerel başarı CI başarısı sayılmaz.

## Kaynaklar

[Resmî SDK OAuth kodu](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/src/mcp/client/auth/oauth2.py)
giriş kodu ve PKCE uygulamasını içerir.
[Keycloak MCP kılavuzu](https://www.keycloak.org/securing-apps/mcp-authz-server)
`resource-indicators` özelliğini açıklar.

Gerçek okurla denenmedi.
