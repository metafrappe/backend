# G-48 devir notu: dosya yükleme güvenliği

Bu not G-48 gereksiniminin P1 kısmını anlatır. S3 pilotu P2 işidir. Bu dal S3 işini yapmaz.

## Ne yapıldı

Kiracı sitesi yükleme güvenliği ayarlarıyla açılır. Ayarları `platform_core/config/turkey_setup.py` yazar. Bu kod G-41 Türkiye ayarlarını da yazar. Aynı iki kanca kodu çağırır: `setup_wizard_complete` ve `after_migrate`. Bu yüzden `hooks.py` değişmedi.

System Settings içinde şu değerler yazılır:

- `max_file_size` değeri 25 olur. Birim MB'dir.
- `strip_exif_metadata_from_uploaded_images` değeri 1 olur.
- `allow_guests_to_upload_files` değeri 0 olur.
- `only_allow_system_managers_to_upload_public_files` değeri 1 olur.
- `allowed_file_extensions` alanına izinli uzantılar yazılır.

Kod yalnız farklı olan değeri yazar. İkinci koşu hiçbir şeyi değiştirmez.

## Uzantı listesi

Orkestratör listeyi 25 Kasım 2026 Çarşamba günü seçti. Karar sonradan değişebilir.

İzinli uzantılar şunlardır: pdf, jpg, jpeg, png, webp, gif, heic, csv, txt, xlsx, xls, ods, docx, doc, odt, pptx, xml, zip.

- `xml` izinlidir. E-fatura ve e-arşiv dosyaları XML'dir.
- `svg`, `html`, `htm` ve `js` izinli değildir. Bu dosyalar tarayıcıda kod çalıştırabilir.
- Çalıştırılabilir dosyalar da izinli değildir.

Liste `turkey_setup.py` içindeki `ALLOWED_FILE_EXTENSIONS` değeridir. Karar değişirse listeyi yalnız orada değiştirin. Sonra `ALLOWED_EXTENSIONS` test değerini de değiştirin.

Kod uzantıları büyük harfe çevirir. Her uzantıyı ayrı satıra yazar. Frappe uzantıyı bu biçimde karşılaştırır. Liste boş olursa kod sitedeki değere dokunmaz.

## Testler

Birim testleri `dev/tests/test_turkey_setup_defaults.py` dosyasındadır. Testler sahte Frappe ile koşar. Her ayar için ayrı bir test vardır.

Gerçek site testi `platform_core/tests/test_upload_security.py` dosyasındadır. Test dört şeyi dener:

- Beş ayarın sitede doğru değeri alması denenir.
- Misafirin dosya yükleme isteği `PermissionError` ile reddedilir.
- Listede olmayan `.exe` uzantısı `FileTypeNotAllowed` ile reddedilir.
- Karar verilen listede `.svg` ve `.html` reddedilir. `.csv` kabul edilir.

Gerçek site testi bu dalda koşulmadı. Bilgisayarın yükü 8'in üstündeydi. Test `dev/bin/test` ile ayrı test sitesinde koşar.

## Canlı adım

Bu adımı DevOps sorumlusu yapar. Bu dal canlı sunucuya dokunmadı.

1. Değişiklik bir kiracı sitesine dağıtılır.
2. DevOps sorumlusu sitede `bench --site <site> migrate` komutunu koşar.
3. DevOps sorumlusu System Settings değerlerini okur.

Kabul ölçütü şudur:

- Beş ayar yukarıdaki değerleri alır.
- Misafir `/api/method/upload_file` isteği reddedilir.
- `.svg` ve `.html` uzantılı dosya reddedilir.

## Bilinen sınırlar

- Depolama kotası `Site Plan.max_storage_usage` ile izlenir. Bu dal kotaya dokunmadı.
- `after_migrate` test sitesinde de misafir yüklemesini kapatır. Misafir yüklemesini bekleyen bir test kendi ayarını açmalıdır.
