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
Bu değer, tam kaynak adresiyle kayıtlı Keycloak istemcisinin sırrıdır.
Frappe, Keycloak sertifikasına da güvenmelidir.
Ayrı Compose ağında `identity.localhost` adı Keycloak kabının ağ takma adıdır.
Bu ad Frappe kabına değil, Keycloak kabına çözülür.
7400 ortamındaki ayarları değiştirmeyin. Bu ortamı yeniden başlatmayın.

## Kurulum ve çalıştırma

Komutları bu işin Git çalışma klasöründe çalıştırın.
`MCP_TEST_VENV` değişkeni çalışma klasörü dışındaki sanal ortamı göstermelidir.
Sanal ortam, Python paketlerini ayrı tutan klasördür.

```bash
uv venv --python ~/.local/bin/python3.14 "$MCP_TEST_VENV"
uv pip sync --require-hashes --python "$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/requirements.lock.txt
```

Örnek hesabın parolasını `MCP_TEST_PASSWORD` ortam değişkeniyle verin.
Parolayı komuta, Git'e veya görev yorumuna yazmayın.
`MCP_TEST_CA` değişkeni yerel test sertifikasının dosya yoludur.

```bash
"$MCP_TEST_VENV/bin/python" e2e/mcp_oauth/client.py \
  --resource https://tenant1.localhost:7841/api/method/platform_core.api.ai.mcp \
  --issuer https://identity.localhost:7840/realms/platform \
  --callback http://127.0.0.1:7842/callback \
  --username mcp-e2e-reader@example.test \
  --ca-file "$MCP_TEST_CA"
```

Betik giriş formunu örnek hesapla doldurur. Ardından erişim iznini onaylar.
Bu işlem parola izni akışı değildir. SDK giriş kodunu PKCE ile değiştirir.
SDK sonra `plt_search_doctypes` aracını çağırır.
Betik geçersiz belirteçle aynı aracı çağırır. Sunucu 401 döndürmelidir.
Betik bu deneme için gerçek belirtecin imzasını bozar.
Betik yalnız sonuç özetini yazar. Parola, kod, belirteç ve araç verisi yazılmaz.
Her çalışma yeni giriş yapar. Belirteçler yalnız bellekte tutulur.
Yanlış parola tekrar gönderilmez. Bütün akışın bekleme sınırı 120 saniyedir.
MCP yanıtının bekleme sınırı 20 saniyedir.

[Yerel kanıt kaydı](../../docs/evidence/mcp-oauth-client.md) sürümleri ve sonuçları gösterir.

## Test kilidi

Testler ve altı dal kapısı ortak kilidi kullanır. Aynı anda test koşturmayın.
Kilidi almadan aşağıdaki komutu çalıştırmayın.

```bash
"$MCP_TEST_VENV/bin/python" -B -m unittest discover -s e2e/mcp_oauth/tests
```

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
