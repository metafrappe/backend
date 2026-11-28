# G-27: press_tr MCP sunucusunu canlı Press'te açma

Bu not DevOps sorumlusu içindir. Not 28 Kasım 2026 Cumartesi günü yazıldı. Not, canlı Press'te yapılacak işi anlatır. Geliştirici canlı Press'e dokunmadı.

MCP, yapay zekâ aracının bir sunucudaki araçları çağırma yöntemidir. press_tr MCP sunucusu Press'in yanında çalışan ikinci MCP sunucusudur. Sunucunun adresi `/api/method/press_tr.mcp.handler` yoludur.

## Sunucudaki araçlar

Sunucuda sekiz araç vardır:

- `list_marketplace_apps`
- `get_app_plans`
- `install_app`
- `change_app_plan`
- `change_site_plan`
- `get_invoices`
- `get_upcoming_invoice`
- `get_agent_job_status`

Üç araç siteyi ya da faturayı değiştirir. Bunlar `install_app`, `change_app_plan` ve `change_site_plan` araçlarıdır. Bu araçlar `confirm` değeri `true` değilse yalnız önizleme döndürür.

## Sunucu ne zaman isteği kabul eder

Sunucu isteği yalnız üç koşul birlikte sağlanırsa kabul eder:

1. Press ayarında MCP açıktır.
2. İsteği ayrı MCP servis hesabı gönderir.
3. İstek izinli bir ağdan gelir.

Sunucu reddedilen isteği de geçmişe yazar. Geçmiş, “PTR MCP Call” listesidir.

## Ön koşul

- press_tr uygulamasının bu sürümü sitede kuruludur.
- Site için `bench migrate` komutu çalışmıştır. Komut “PTR MCP Call” tablosunu açar.
- Bu değişiklik canlı ortamda onaylı bir değişikliktir. Önce ortamın sorumlusundan onay alın.

## Adımlar

1. DevOps sorumlusu Press'te yeni bir kullanıcı açar. Örnek ad `mcp-agent@<alan adı>` olabilir. Kullanıcının türü “System User” olur.
2. DevOps sorumlusu bu kullanıcıya yalnız “System Manager” rolünü verir.
3. DevOps sorumlusu bu kullanıcı için bir API anahtarı ve gizli değer üretir. Değerler Git'e ve sohbete yazılmaz. Değerler gizli değer kasasında durur.
4. DevOps sorumlusu servis hesabının adını site ayarına yazar:

   ```bash
   bench --site <site> set-config press_tr_mcp_service_user "mcp-agent@<alan adı>"
   ```

5. DevOps sorumlusu izinli ağları site ayarına yazar. Değer bir listedir. Her öğe bir IP adresi ya da ağ aralığıdır:

   ```bash
   bench --site <site> set-config --parse press_tr_mcp_allowed_networks '["<ajan ağı>/32"]'
   ```

   Liste boşsa sunucu her isteği reddeder. Yanlış yazılmış bir öğe hiçbir ağa izin vermez.

6. DevOps sorumlusu Press ayarında MCP'yi açar. “Press Settings” ekranında “Enable MCP” kutusunu işaretler.
7. DevOps sorumlusu ters vekil sunucunun gerçek istemci adresini Frappe'ye ilettiğini denetler. Frappe adresi `X-Forwarded-For` başlığından okur. Başlık yanlışsa ağ izni yanlış adresi denetler.

## Doğrulama ölçütü

DevOps sorumlusu şu denemeleri izinli ağdaki bir makineden yapar:

1. Servis hesabının anahtarıyla `tools/list` isteği gönderin. Yanıtta sekiz aracın adı bulunmalıdır.
2. `install_app` aracını `confirm` olmadan çağırın. Yanıtta `"preview": true` bulunmalıdır. Sitede yeni uygulama kurulmamalıdır.
3. Aynı isteği başka bir “System Manager” hesabıyla gönderin. Sunucu 401 yanıtı vermelidir.
4. Aynı isteği izinli olmayan bir ağdan gönderin. Sunucu 401 yanıtı vermelidir.
5. “PTR MCP Call” listesini açın. Her deneme için bir satır olmalıdır. Önizleme satırının durumu “Preview” olmalıdır. Reddedilen isteklerin durumu “Refused” olmalıdır.

Bir adım ölçütü karşılamazsa MCP'yi kapatın. “Enable MCP” kutusunun işaretini kaldırın. Sonra sorunu geliştirme ekibine bildirin.

## Geri alma

1. “Press Settings” ekranında “Enable MCP” kutusunun işaretini kaldırın.
2. Servis hesabının API anahtarını silin.
3. İsterseniz servis hesabını devre dışı bırakın.

Bu adımlar Press'in kendi MCP sunucusunu da kapatır. İki sunucu aynı ayarı kullanır.
