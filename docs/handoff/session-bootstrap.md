# Panel oturumu ve başlangıç verisi

## Üretim doğrulaması

DevOps sorumlusu, panel ve operatör adreslerini ayrı tutar.
Operatör adresine erişimi Tailscale ağıyla sınırlar.
Ayrı adresler, panel ve operatör oturumlarının çerezlerini ayırır.

1. Panel adresinde oturum açın.
2. Oturum çerezinde `Domain` alanının gelmediğini doğrulayın.
3. Anlık olay bağlantısının panel adresindeki `/socket.io/` yolunu kullandığını doğrulayın.
4. Operatör adresinin kendi oturum çerezini kullandığını doğrulayın.
5. Özel ağ dışından operatör adresine erişimin kapalı olduğunu doğrulayın.

Yerel yapılandırma testi, iki adres için ayrı servis bağlantılarını denetler.
Canlı çerez ve anlık olay kanıtı için çalışan deneme sunucusu gerekir.

## Kiracı kurulumu

Yerel test, `platform_core` kurulum ve güncelleme bağlantılarını denetler.
Test, hazır rol kaydında yalnız izin verilen alanların bulunduğunu doğrular.
Kurulum ve güncellemenin sonucu için ayrı bir Frappe test sitesi gerekir.

## Geçici veri

Başlangıç verisinin önbelleği site ve kullanıcıya özeldir.
Kiracı siteleri ayrı oturum kullanır.
Çıkışta sunucu iki kaydı hemen siler (O-64).
Birincisi oturumun etkinlik anahtarıdır.
İkincisi kullanıcının başlangıç verisi önbelleğidir.
Yerel testler bu silmeyi tek sitede sınar.
Yerel test, başka site önekli anahtarın kaldığını da sınar.

Gerçek iki siteli deneme koşmadı.
Deneme 25 Kasım 2026 Çarşamba günü de koşmadı.
Bu deneme için iki ayrı Frappe test sitesi gerekir.
İki site aynı Redis'i kullanmalı.
Yerel test ortamı her uygulama için tek site kurar.
Örneğin `dev/bin/test platform_core` yalnız `test-platform-core.localhost` sitesini kurar.
Yerel ortamda iki siteyi aynı anda sunan bir web sunucusu yok.
Bu yüzden deneme yerelde yapılamadı.
İki siteli ortamı kurmak ayrı bir iştir.
Canlı sunucu bu deneme için kullanılmaz.
Deneme adımları şunlardır:

1. A ve B sitelerinde aynı kullanıcıyla oturum açın.
2. İki sitede de başlangıç verisini bir kez isteyin.
3. A sitesinde `platform_core.api.auth.logout` ucunu çağırın.
4. A sitesinin iki kaydının Redis'te olmadığını doğrulayın.
5. B sitesinin kayıtlarının yerinde durduğunu doğrulayın.
6. B sitesindeki oturumun açık kaldığını doğrulayın.

Tarayıcıdaki geçici verinin temizlenmesi kapsam dışı: atonota-web.
