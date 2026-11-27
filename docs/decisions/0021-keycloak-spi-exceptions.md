# 0021. Keycloak SPI istisnaları ve realm fark raporu (G-152)

Durum: taslak. Kararı Team SAFe PM verir. Taslağı Team A mimarı 28 Kasım 2026 Cumartesi günü yazdı (AJA-2290).

## Terimler

- SPI, Keycloak'a Java ile eklenen eklenti noktasıdır. Eklenti bir jar dosyası olarak imaja girer.
- Realm, Keycloak'taki giriş ayarlarının bütünüdür. İstemciler, roller ve giriş akışları realm içindedir.
- Fark raporu, çalışan realm ile Git'teki realm dosyasının farkını listeler.

## Sorun

G-152 kuralı iki şey ister:

1. Özel SPI yazılmaz. Tek istisna identity-sync olay köprüsüdür.
2. Realm ayarları Git'ten gelir. Elle yapılan değişiklik fark raporunda görünür.

Depo bu kurala uymuyor. İmajda olay köprüsünden başka altı eklenti var. Ayrıca üretim Keycloak'ı `--import-realm` ile açılır (`deploy/compose/stack.yaml`). Bu ayar var olan realm'i atlar. Bu yüzden Git'teki değişiklik üretime ulaşmaz. Elle yapılan değişiklik de hiçbir yerde görünmez.

## Öneri özeti

| Eklenti | Öneri | Kısa gerekçe |
| --- | --- | --- |
| identity-sync olay köprüsü | Kalsın. G-152'nin tek istisnasıdır. | Kural bu köprüye açıkça izin verir. |
| Hesap ekranı kapsam kancası | Kaldırılsın. | Realm verisini Java ile değiştirir. Bu iş realm dosyasının işidir. |
| Güvenlik başlığı sağlayıcısı | Kaldırılsın. | Aynı sonuç realm ayarıyla alınabilir. Güvenlik incelemesi gerekir. |
| MCP kaynak ve dönüş denetimi | Geçici istisna olsun. | Belirteç güvenliğini sağlar. Ayarla yapılan bir yol bulunamadı. |
| Sihirli bağlantı | Geçici istisna olsun. | Şifresiz giriş ürün özelliğidir. Hazır yayın yoktur. |
| Hesap silme bağlantısı | Geçici istisna olsun. | G-152 temayı Keycloakify ile ister. O tema henüz yok. |
| Apple ile giriş | Geçici istisna olsun. | Keycloak'ta yerleşik Apple sağlayıcısı yoktur. Kodu biz yazmadık. |

Her eklentinin ayrıntısı aşağıdaki listededir. `dev/tests/test_keycloak_spi_decision.py` bu listeyi denetler. Test imajdaki her jar dosyasını arar. Depodaki her `META-INF/services` kaydını da arar. Listede olmayan yeni bir eklenti testi düşürür.

## Eklenti listesi

```json
{
  "keycloak_spi_inventory": {
    "status": "draft",
    "decider": "Team SAFe PM",
    "keycloak_version": "26.8.2",
    "extensions": [
      {
        "id": "identity-sync-event-listener",
        "g152_bridge": true,
        "spi": "org.keycloak.events.EventListenerProviderFactory",
        "provides": ["au.com.ais.keycloak.webhook.WebhookEventListenerProviderFactory"],
        "source": "repository",
        "jar": "keycloak-webhook-listener-identity-sync.jar",
        "recommendation": "keep_exception",
        "reason": "G-152 allows exactly this bridge. It signs user and admin events for the identity-sync service.",
        "contract_test": "identity/keycloak/event-listener JUnit tests and identity/keycloak/tests/test_event_listener.py",
        "exit": "Replace with admin event polling if the bridge breaks on a Keycloak minor upgrade."
      },
      {
        "id": "account-console-scope-hook",
        "spi": "org.keycloak.events.EventListenerProviderFactory",
        "provides": ["net.atonota.keycloak.account.AccountConsoleScopeFactory"],
        "source": "repository",
        "jar": "keycloak-webhook-listener-identity-sync.jar",
        "recommendation": "remove",
        "reason": "It changes realm data from Java when the realm is created. G-152 wants realm data from the Git file only.",
        "contract_test": "identity/keycloak/tests/test_realm_backlog.py and test_live_keycloak.py until removal",
        "exit": "The realm apply step adds the roles scope to account-console. Then delete the class and its service line."
      },
      {
        "id": "platform-security-headers",
        "spi": "org.keycloak.headers.SecurityHeadersProviderFactory",
        "provides": ["net.atonota.keycloak.headers.PlatformSecurityHeadersFactory"],
        "source": "repository",
        "jar": "keycloak-webhook-listener-identity-sync.jar",
        "recommendation": "remove",
        "reason": "It only drops frame-ancestors none on three Keycloak probe pages. A realm header value can reach the same result.",
        "contract_test": "identity/keycloak/tests/test_realm_files.py and test_realm_backlog.py header checks",
        "exit": "Set the realm CSP to frame-ancestors self after a security review, then delete the provider."
      },
      {
        "id": "mcp-oauth-resource",
        "spi": "org.keycloak.services.clientpolicy.executor.ClientPolicyExecutorProviderFactory and org.keycloak.protocol.ProtocolMapper",
        "provides": [
          "net.atonota.keycloak.mcp.McpResourcePolicyFactory",
          "net.atonota.keycloak.mcp.McpRedirectPolicyFactory",
          "net.atonota.keycloak.mcp.McpExplicitResourceMapper"
        ],
        "source": "repository",
        "jar": "keycloak-webhook-listener-identity-sync.jar",
        "recommendation": "temporary_exception",
        "reason": "Decision 0017 needs one signed MCP resource per token. No realm setting for this check was found in this repository.",
        "contract_test": "identity/keycloak/tests/test_mcp_oauth.py, test_mcp_redirect.py and McpRedirectTest JUnit",
        "exit": "Remove when Keycloak checks the resource parameter itself, or when the platform checks it outside Keycloak."
      },
      {
        "id": "magic-link",
        "spi": "org.keycloak.authentication.AuthenticatorFactory",
        "provides": ["magiclink"],
        "source": "upstream_fork",
        "jar": "keycloak-magic-link-7b4ee94.jar",
        "recommendation": "temporary_exception",
        "reason": "Passwordless sign-in is a product feature from decision 0003. Upstream has no release, so we build a pinned fork.",
        "contract_test": "identity/keycloak/tests/test_magic_link.py on every Keycloak minor upgrade",
        "exit": "Use an upstream release for the running Keycloak line, or a built-in Keycloak sign-in link."
      },
      {
        "id": "account-deletion-link",
        "spi": "org.keycloak.services.resource.AccountResourceProviderFactory",
        "provides": ["platform.identity.account.AccountDeletionLinkConsoleFactory"],
        "source": "repository",
        "jar": "account-deletion-link-provider.jar",
        "recommendation": "temporary_exception",
        "reason": "G-152 wants the theme from Keycloakify without Java. That account theme does not exist yet, and the deletion link must stay.",
        "contract_test": "identity/keycloak/tests/test_account_backlog.py and AccountDeletionLinkConsoleCheck",
        "exit": "Move the link into a Keycloakify account theme. Keep the visibility decision on the server side."
      },
      {
        "id": "apple-identity-provider",
        "spi": "org.keycloak.broker.social.SocialIdentityProviderFactory",
        "provides": ["apple"],
        "source": "third_party_release",
        "jar": "apple-identity-provider-1.17.0.jar",
        "recommendation": "temporary_exception",
        "reason": "Keycloak has no built-in Apple provider. We use a pinned release jar and write no code for it.",
        "contract_test": "identity/keycloak/tests/test_extensions.py provider registration check",
        "exit": "Remove when Keycloak ships a built-in Apple provider."
      }
    ]
  }
}
```

## Eklentilerin gerekçesi

### identity-sync olay köprüsü

Bu eklenti kullanıcı ve yönetim olaylarını imzalar. Sonra olayları identity-sync servisine gönderir. Seçim gerekçesi 0003 kararındadır. G-152 bu köprüye açıkça izin verir. Bu yüzden köprünün kalmasını öneriyoruz.

### Hesap ekranı kapsam kancası

Bu sınıf bir olay dinleyicisi gibi kayıtlıdır. Ama olay dinlemez. Realm ilk kurulunca `account-console` istemcisine `roles` kapsamını ekler. Keycloak bu istemciyi kapsamlardan önce kurar. Bu yüzden realm dosyası bu bağı ilk içe almada kuramaz.

Bu kancanın kaldırılmasını öneriyoruz. Realm uygulama adımı bu bağı kurabilir. `identity/keycloak/bin/sync-dev-realm.py` istemci kapsamlarını zaten bağlar. Bu adım üretimde de koşunca kanca gereksiz olur.

### Güvenlik başlığı sağlayıcısı

Realm dosyası `frame-ancestors 'none'` kuralını yazar. Bu kural Keycloak'ın üç yoklama sayfasını bozar. Örneğin `login-status-iframe.html` sayfası çerçeve içinde açılamaz. Sağlayıcı bu üç sayfada kuralı siler.

Bu sağlayıcının kaldırılmasını öneriyoruz. Realm kuralı `frame-ancestors 'self'` olabilir. Bu, Keycloak'ın kendi varsayılanıdır. Bu kural yalnız aynı adresin çerçevesine izin verir. Bu değişiklik güvenlik incelemesinden geçmelidir. Bu yüzden karar sorularına eklendi.

### MCP kaynak ve dönüş denetimi

Bu üç sınıf MCP belirtecini korur. Belirteç yalnız tek bir siteye yazılır. Dönüş adresi de denetlenir. Gerekçe 0017 kararındadır. Bu depoda aynı denetimi realm ayarıyla yapan bir yol bulunamadı.

Bu sınıflar geçici istisna olsun. Bu sınıflar kalkarsa bir belirteç başka sitede kullanılabilir. Bu güvenlik açığı olur.

### Sihirli bağlantı

Şifresiz giriş ürün özelliğidir. Eklentinin yayımlanmış sürümü yoktur. Kaynak sabit bir commit'ten derlenir. G-162 düzeltmeleri çatalda durur. Gerekçe 0003 kararındadır.

Bu eklenti geçici istisna olsun. Her Keycloak alt sürümünde `test_magic_link.py` koşmalıdır.

### Hesap silme bağlantısı

Bu sağlayıcı hesap ekranına silme bağlantısı koyar. Bağlantının görünüp görünmeyeceğine sunucu karar verir. G-152 temayı Keycloakify ile ister. Keycloakify hesap teması henüz yok.

Bu sağlayıcı geçici istisna olsun. Keycloakify teması gelince bağlantı temaya taşınır.

### Apple ile giriş

Keycloak'ta yerleşik Apple sağlayıcısı yok. Hazır bir yayın kullanılır. Sürüm ve SHA-256 özeti Dockerfile'da sabittir. Bu eklentinin kodunu biz yazmadık. Ama imajda bir SPI olduğu için listededir.

Bu eklenti de geçici istisna olsun.

## Realm fark raporu

### Bugünkü durum

- Üretim `start --import-realm` ile açılır. Realm veritabanında varsa dosya içe alınmaz.
- `sync-dev-realm.py` farkı kapatır. Ama yalnız yerel Keycloak'ta çalışır. Rapor da üretmez, doğrudan yazar.
- `origin/pc/aja29-press-calls-tests` dalında `identity/keycloak/tests/test_press_realm_drift.py` testi var. Bu dal henüz main dalında değil. Test bellekteki sahte Admin API ile çalışır. İstemci sapmasını kurar ve senkronun düzelttiğini gösterir. Sonra ikinci koşunun hiç yazmadığını gösterir.

### Önerilen yöntem

1. `sync-dev-realm.py` dosyasına salt okunur bir rapor kipi eklenir. Kip adı `--report` olur.
2. Rapor kipi aynı karşılaştırma işlevlerini kullanır. Yazma çağrıları yapılmaz. Bunların yerine fark listesi toplanır.
3. Rapor şu parçaları karşılaştırır: realm ayarları, istemciler, istemci kapsamları, eşleyiciler, roller, giriş akışları, kimlik sağlayıcıları.
4. Kullanıcılar ve oturumlar karşılaştırılmaz.
5. Rapor yalnız öğe adını ve alan adını yazar. Sır değeri yazmaz.
6. Fark varsa komut 1 ile çıkar. Fark yoksa 0 ile çıkar.
7. Rapor kipi yalnız okuma izni olan bir hesapla çalışır. Örneğin `view-realm` ve `view-clients` rolleri yeterlidir.
8. Yerel adres sınırı yalnız yazma kipinde kalır. Rapor kipi test ortamında da koşabilir.

### Rapor kipinin testi

`test_press_realm_drift.py` testindeki sahte Admin API yöntemi kullanılır. Test önce sapma kurar. Sonra raporun sapmayı listelediğini denetler. Ayrıca raporun hiç yazma çağrısı yapmadığını denetler. Sapma yoksa rapor boş dönmelidir.

### Raporun koşacağı yer

- Rapor her sürümden önce test ortamında koşar. Fark varsa sürüm durur.
- Üretimde rapor koşmak ayrı ve onaylı bir iştir. Bu taslak canlı sunucuya dokunmaz.
- G-152 haftalık rapor ister. Haftalık koşu zamanlanmış iş demektir. Kullanıcı kararı zamanlanmış işi yasaklar. Bu yüzden haftalık koşu karar sorularındadır.

## Alt sürüm sözleşme testi

Keycloak sürümü tek yerde yazılır: `identity/keycloak/Dockerfile` içindeki `KEYCLOAK_VERSION`. Bugünkü değer 26.8.2'dir.

Önerilen test dört adımdan oluşur:

1. Her eklenti aday Keycloak sürümüyle Maven'da derlenir. Keycloak iç API'si değişirse derleme düşer.
2. Eklentilerin JUnit birim testleri koşar.
3. İmaj açılır. Test `/admin/serverinfo` yanıtını okur. Listedeki her eklenti kimliği yanıtta olmalıdır. Yanıtta listede olmayan özel eklenti varsa test düşer.
4. Her eklentinin listede yazan sözleşme testi koşar.

Testi CI'daki bir iş koşar. İş iki sürümle koşar: bugünkü sürüm ve bir sonraki alt sürüm adayı. `KEYCLOAK_VERSION` değeri değişen bir PR bu iş geçmeden birleşmez. Backend CI henüz main dalında değil (AJA-2135). Bu iş o CI gelince eklenir.

## Karar için sorular

PM şu soruları yanıtlamalıdır:

1. Yukarıdaki yedi öneri kabul mü?
2. Realm güvenlik başlığı `frame-ancestors 'self'` olabilir mi? Bu soru için güvenlik incelemesi gerekir.
3. Fark raporu yalnız sürümden önce mi koşsun? Haftalık koşu için kullanıcının açık cron kararı gerekir.
4. Geçici istisnalar G-152 metnine yazılsın mı? Bu, `frappesetup` deposundaki gereksinim kaydını değiştirir.

## Sonraki işler

Karar verilince şu işler açılır:

1. Rapor kipi ve testi.
2. Hesap ekranı kapsam kancasının kaldırılması.
3. Güvenlik başlığı sağlayıcısının kaldırılması.
4. Alt sürüm sözleşme testi işi. Bu iş backend CI'ı bekler.
