# AJA-85 ara teslim kaydı

Dal `pc/ai-service-setup` adındadır.
Taban commit `d54673d058a86b8af97f7589d3263060892461d1` olur.
Bu dal henüz birleştirmeye hazır değildir.
G-83 ve G-88 kapanmadı.

Bu kayıt 28 Kasım 2026 Cumartesi günü bu depoya taşındı. Taşıma işi AJA-2436 oldu.
Taşımada G-88 uygulama kodu yoktu. `test_page_context.py` bu kod yazılınca geçer.

## Yapılan iş

- Yerel model geçidi için Compose tanımı hazırlandı.
- Veritabanı ve kalıcı kuyruk tanıma eklendi.
- Caddy ile yerel şifreli bağlantı tanımı eklendi.
- Kurulum ve model seçimi testleri yazıldı.
- G-88 bağlam sözleşmesi ve HTTP testleri yazıldı.
- Hüseyin Cengiz için devir notu hazırlandı.
- AJA-111 görevinde bağımsız mimari görüş alındı.

G-88 uygulama kodu yazılmadı.
Önce düşen test koşmadan davranış değiştirilmedi.

## Engel

Ortak kilidin sahibi AJA-47 olarak görünür.
Kilit dosyası `kapi-kilidi/sahip` adındadır.
Dosya eski yerel deponun `.pane/scratch` klasöründedir.
Kilit, 23 Kasım 2026 Pazartesi günü saat 20:20:18'de yazılmıştır.
Saat Türkiye saatidir.
AJA-47'nin güncel çalışması API yanıtında `queued` durumundadır.
Bu durum, çalışmanın sırada beklediğini belirtir.
Çalışmanın kimliği `259d12c5-436c-42da-81a5-4076165bb604` olur.

Kilit başka görev adına olduğu için değiştirilmedi.
AJA-47 görevine koordinasyon yorumu yazıldı.
Platform, PO ajanına alt görev atamasını reddetti.
Gerekçe, görevi veren ajana tekrar alt görev verilmesidir.
Bu nedenle mevcut iş PO ajanına geri verilir.

## Gerçek kontroller

| Kontrol | Sonuç | Kanıtın sınırı |
| --- | --- | --- |
| Yerel Compose testi | `fail` | Tanım henüz yokken beklenen dosya hatası çıktı. |
| Kiracı ve Caddy imaj derlemesi | `pass` | İki yerel imaj derlendi. |
| Yerel test sitesi kurulumu | `pass` | `platform_core` ayrı test sitesine kuruldu. |
| Yerel servisleri başlatma | `pass` | Compose komutu sıfır koduyla bitti. |
| Şifreli HTTP doğrulaması | `not_run` | Kilit bekleniyor. Başlatma sonucu bu doğrulamanın yerine geçmez. |
| G-88 önce düşen test | `not_run` | Ortak kilit nedeniyle çalıştırılmadı. |
| Model seçimi testleri | `not_run` | Ortak kilit nedeniyle çalıştırılmadı. |
| Altı dal kapısı | `not_run` | Ortak kilit nedeniyle çalıştırılmadı. |
| Türkçe metin betiği | `not_run` | Ara teslimde otomatik kontrol yapılmadı. Metin elle denetlendi. |
| Bağımsız kod incelemesi | `not_run` | Uygulama kodu henüz hazır değil. |
| Hetzner doğrulaması | `not_run` | Canlı sunucuya dokunulmadı. |
| Arayüz doğrulaması | `not_applicable` | Kapsam dışı: atonota-web. |

İlk Compose testi kilit alınamamasına rağmen yanlışlıkla çalıştırıldı.
Test yalnız eksik yerel dosya nedeniyle düştü.
Bu çalıştırma dal kapısı geçişi sayılmadı.
Sonraki test denemeleri kilit kontrolünde durdu.

Çalıştırılan test komutu şöyledir:

```bash
~/.local/bin/python3.14 -B -m unittest discover -s dev/tests -p test_ai_service.py
```

Derleme, başlangıç ve site kurulum komutları devir notunda yer alır.
Bu çalışmada Compose proje adı `fs-ai-service-aja85` oldu.
Test sitesi `test-platform-core.localhost` oldu.
İşin konteynerleri ara teslimde kapatılır. Kalıcı birimler korunur.
Yerel çalışma Python 3.14.10 ve Frappe 16.56.0 kullandı.
Pydantic sürümü 2.12.5, Ruff sürümü 0.14.10 çıktı.
Manifest Python aralığı `>=3.14,<3.15` olur.
Manifest Frappe aralığı `>=16.56.0,<17.0.0` olur.
Python bağımlılıklarının ayrı kilit çözümü doğrulanmadı.

Frappe'nin gerçek kaynakları şu davranışı doğruladı:

- `frappe/mcp/tools/__init__.py:55`, bilinmeyen alanları ve tür dönüşümünü reddeder.
- `frappe/model/document.py:635`, `check_permission` ile kayıt iznini denetler.

## Devam sırası

1. PO ajanı ortak kilidin gerçek sahibini netleştirsin.
2. DevOps ajanı kilit boşalınca kilidi alsın.
3. DevOps ajanı G-88 testini gerçek HTTP yolunda çalıştırsın.
4. DevOps ajanı beklenen bağlam hatasını kaydetsin.
5. DevOps ajanı mevcut MCP çağrısına bağlam denetimini eklesin.
6. DevOps ajanı altı dal kapısını sırayla çalıştırsın.
7. DevOps ajanı yerel şifreli bağlantıyı sertifika doğrulamasıyla sınasın.
8. DevOps ajanı değişen Markdown dosyalarında Türkçe denetimini çalıştırsın.
9. Bağımsız inceleyici gerçek farkı ve test kanıtını incelesin.

Son inceleme, komut çalıştırmadan ve dosya değiştirmeden yapılır.
Gerçek okurla denenmedi.
