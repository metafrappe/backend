# Özellik kapısı devri

G-35, G-106 ve G-127 bu çalışmanın kapsamındadır.

## Kurulum

1. Press adresini kiracı ayarındaki `press_subscription_url` alanına yazın.
2. Press'in eklediği `sk_<app>` alanını kullanın.
3. Uygulama ayarını `platform_subscriptions` altında uygulama adıyla açın.
4. `permission_doctype` alanına uygulamanın ana kayıt türünü yazın.
5. Kiracı yöneticisinin seçimini `enabled` alanına yazın.
6. Press plan adını `plans` altında anahtar olarak kullanın.
7. Planın özelliklerini `features` listesine yazın.
8. Yazmayı kapatan planlarda `read_only` alanını `true` yapın.

Press, ön ödemeli denemenin bitişini `subscription.expiry` alanına yazar.
Saat dilimi yoksa kod, kiracı sitesinin saat dilimini kullanır.
Press ve kiracı saat dilimini eşleştirin.
Deneme planının adını `trial_plan` alanına yazın.
Böylece deneme bitişi yeni planı etkilemez.
Press yanıtı site adı içermeyebilir.
Bu durumda Press'in siteye yazdığı uygulama anahtarı kullanılır.
Deneme ayarındaki anahtar da aynı uygulamaya ait olmalıdır.
Press uygulama için bitiş vermiyorsa `trial_ends_at` alanına Unix saniyesi yazın.
Bu sayı, UTC ile 1 Ocak 1970'ten beri geçen saniyedir.

## Uygulama bağlantısı

- Arayüz, `platform_core.subscription.feature_decision` adresini girişten sonra çağırır.
- Sunucu, bu çağrıda seçilen kayıt türünün okuma iznini denetler.
- Sunucu işlemi, `require_feature(app, feature)` kapısını çağırır.
- Frappe API işlevinde `@frappe.whitelist` satırını kapının üstüne koyun.
- Kayıt olaylarında aynı kapıyı uygulamanın kayıt işleyicisine ekleyin.
- Mevcut veriyi okuyan işlevde `operation="read"` kullanın.
- Dışa aktarma işlevinde `operation="export"` kullanın.
- Mevcut veriyi okuyan işlevde `operation="read"` kullanın.
- Dışa aktarma işlevindeki kayıt izinlerini koruyun.

## Deneme sunucusunda doğrulama

1. İki deneme sitesine farklı planlar bağlayın.
2. Her sitede dönen planı Press kaydıyla karşılaştırın.
3. Press'te üst plandan alt plana geçin.
4. 60 saniye sonra özellik kararını yeniden okuyun.
5. Deneme süresini bitirin ve özelliğin kapandığını doğrulayın.
6. Aboneliği askıya alın ve yazma isteği gönderin.
7. Sunucunun 403 döndürdüğünü doğrulayın.
8. Yetkili hesapla veri dışa aktarın.
9. Yetkisiz hesabın aynı veriyi alamadığını doğrulayın.

Press yalnız ERPNext ve HRMS için güncelleme çağrısı gönderir.
Diğer uygulamalar planı en geç 60 saniye sonra yeniden okur.
Güvenilir sunucu kodu `subscription_update_hook()` ile önbelleği temizleyebilir.
DocType değişikliği kayda geçince aynı temizleme çalışır.

Yerel ortamda Press 0.7.0 ve Frappe 16.56.0 kaynakları incelendi.

- `press/api/developer/marketplace.py:14` abonelik anahtarını denetler.
- `press/api/developer/marketplace.py:37` yanıt alanlarını seçer.
- `press/api/developer/__init__.py:4` geçersiz anahtar için 401 tanımlar.
- `press/press/doctype/site/site.py:1030` uygulama anahtarını kiracı sitesine yazar.
- `frappe/exceptions.py:41` izin hatası için 403 tanımlar.
- `frappe/utils/redis_wrapper.py:52` geçici kaydı siteye göre ayırır.

Gerçek Press denemesi için ayrı bir deneme sunucusu gerekir.
