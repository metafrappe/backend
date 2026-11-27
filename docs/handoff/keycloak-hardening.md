# Keycloak kurulum ve erişim kontrolleri

## Kapsam ve görev sahibi

Bu not, hazırlık ortamında G-76 ve G-144 gereksinimlerini kapsar.
Görev sahibi DevOps sorumlusudur. Platform ekibi uygulamanın giriş testlerine destek verir.
Keycloak, kullanıcıların oturum açmasını sağlayan servistir.

## Bağımlılıklar

- [Hazırlık sunucusu](staging-server.md) çalışmalıdır.
- Özel ağ ve sertifika hazır olmalıdır.
- Ayrı konumdaki yedek deposu ve günlük sunucusu hazır olmalıdır.
- Alan adı kaydı gerekebilir. Bu durumda DevOps sorumlusu kaydın bilgilerini hazırlar. Alan adı sorumlusu kaydı uygular.

## Adımlar

1. Kurulum için desteklenen Keycloak sürümünü doğrulayın. Gereksinimde 26.x hedefi geçer.
2. En az iki Keycloak sunucusunu ortak kümede çalıştırın.
3. PostgreSQL için ikinci sunucuya veri kopyalamayı kurun.
4. Giriş servisini HTTPS ile yayınlayın. RC adresi `api.login.rc.atonota.net` olur.
5. Yönetim yollarını aracı sunucuda açık internete kapatın.
6. Yönetim panelini ve yönetim API'sini yalnız özel ağdan açın.
7. İstemcilerin dönüş adreslerini tam adres olarak kaydedin.
8. Anonim istemci kaydını kapatın. Implicit girişi ve parola ile belirteç almayı da kapatın.
9. Açık istemcilerde PKCE S256 doğrulamasını zorunlu tutun.
10. Gereksiz giriş özelliklerini kapatın.
11. Tekrarlanan hatalı girişlere karşı korumayı açın. Geçiş anahtarı desteğini de açın.
12. Kullanıcı ve yönetici olaylarını günlük sunucusuna aktarın.
13. Günlük şifreli PostgreSQL yedeğini ikinci konumda doğrulayın.

## Doğrulama

- **G-76.** İki Keycloak sunucusunun çalıştığını doğrulayın. PostgreSQL kopyasının güncel olduğunu da doğrulayın. İkinci konumdaki şifreli yedeği ayrı bir deneme veritabanına açın.
- **G-76.** Giriş, çıkış ve hatalı giriş kayıtlarını bulun. E-posta değişikliği ve yönetici olaylarını da günlük sunucusunda bulun. Saklama süresini proje kuralıyla karşılaştırın.
- **G-144.** Açık internetten `/admin` ve `/admin/realms/platform` yollarını deneyin. İki yolda da HTTP 403 bekleyin. 403, sunucunun erişimi engellediğini gösterir.
- **G-144.** Özel ağdan yetkili yönetim erişimini doğrulayın. Ayrı yönetim adresi tek başına açık erişimi engellemez.
- **G-144.** İzinli dönüş adresini ve kapalı giriş yöntemlerini sınayın. Kayıt dışı dönüş adresinin reddedildiğini doğrulayın. Açık istemci varsa PKCE S256 olmayan giriş isteğini deneyin. Bu isteğin reddedildiğini doğrulayın.
- **G-144.** Her sürüm yükseltmesinde kontrolleri RC ortamında tekrarlayın.

## Kabul ölçütü

DevOps sorumlusu iki sunucunun ve ikinci konumdaki yedeğin çalıştığını kaydeder.
Kullanıcı ve yönetici olayları günlük sunucusuna ulaşır.
Açık internetten yönetim yolları 403 döner. Özel ağda yetkili yönetim çalışır.
Giriş testleri izinli adresleri kabul eder. Kapalı yöntemleri ve kayıt dışı adresleri reddeder.

- [Proje kaydı](../../PROJECT-RECORD.md)
- [Keycloak karar belgesi](../decisions/0003-keycloak-extensions.md)
