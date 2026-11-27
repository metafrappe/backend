# AJA-84 kullanım ve kredi devri

Bu iş `pc/ai-usage-credit` dalındadır. İlk taban `d54673d058a86b8af97f7589d3263060892461d1` commit'idir.
Dal daha sonra `18a9fff8dc22368e2e5be0a2c509c0c1a552e648` ucunu aldı.
Kanıt yalnız yerel ortam içindir. Canlı sunucu kullanılmadı.
AJA-133 mimari kararı işin sınırını belirler. O-57 bu sınırı kaydeder.

## Kalan gereksinimler

| Kayıt | Hazırlanan parça | Açık kalan parça |
| --- | --- | --- |
| G-87 | Ortak konuşma izi ve yönetici kullanım özeti eklendi. | Konuşma deposu yoktur. 90 günlük saklama ve çoklu site toplamı açık kalır. |
| G-90 | İlk giden isteğin gizleme testi eklendi. | Hukuki aktarım onayı kod işi değildir. Hukuk sorumlusu aktarım koşullarını onaylar. |
| SA-15 | Tek ücret ve süre aşımı testleri eklendi. | P2 ödeme bağı çözülmedi. P2, MVP kapsamı dışındadır. |

G-87 tamamen kapanmaz. Kullanıcı arayüzü kapsam dışıdır: atonota-web.
Mevcut maskeleme bilinen sayı ve e-posta biçimlerini bulur.
Serbest metindeki her kişi adını veya adresi bulduğu iddia edilmez.

## Yerel test ortamı

Manifest Python için `>=3.14,<3.15` aralığını ister.
Manifest Frappe için `>=16.56.0,<17.0.0` aralığını ister.
Deneme imajı `frappe/erpnext:v16.55.0` olarak seçildi.
İmajda Python 3.14.10 ve Frappe 16.56.0 gözlendi.
Requests 2.33.1 ve Redis 7.1.1 gözlendi.
PyPika 0.51.1 gözlendi. Manifest ayrıca belirli bir Frappe PyPika commit'i ister.
Bu imajın PyPika Git kaynağı doğrulanmadı.
Yeni paket kurulmadı. Çalışan hizmetler yeniden başlatılmadı.

## QA adımları

QA, dalın son commit'ini ayrı test ortamında inceler.

1. QA ortak kapı kilidini alır.
2. QA dal kapılarını sırayla çalıştırır.
3. QA kullanım ve kredi testlerini çalıştırır.
4. QA yalnız ayrı kiracı test sitesinde şemayı günceller.
5. QA gerçek HTTP istekleriyle yönetici özetini dener.
6. QA misafir ve normal kullanıcı reddini doğrular.
7. QA hesap izni kısıtlı yöneticinin yalnız kendi hesabını görmesini doğrular.
8. QA farklı kullanıcıların aynı krediyi eşzamanlı istemesini dener.
9. QA eski kayıtlardaki boş konuşma izini doğrular.
10. QA kilidi bırakır ve sonuçları göreve yazar.

HTTP, ağ üzerinden yapılan sunucu isteğidir.
Birim testindeki istek gövdesi kaydı gerçek ağ yakalaması değildir.
QA, dış sağlayıcı yerine yerel sahte sağlayıcı kullanır.
Hüseyin Cengiz daha sonra ayrı hazırlık ortamını doğrular.
Bu not canlı dağıtım veya gerçek veriyle deneme yetkisi vermez.

## Doğrulama durumu

İlk RED koşusunda telefon ve ondalıklı kimlik açıkları doğrulandı.
İnceleme koşusunda kart ve kayıt izni açıkları doğrulandı.
Bu açıklar için testler eklendi.
AJA-279 kart açığını kapattı. Kart artık başka bir sayıdan sonra da gizlenir.
Kod her sayı grubunda 13 ile 19 haneli bütün adayları dener.
Her başlangıç için en çok 37 karakter taranır. Böylece uzun girdi yavaşlamaz.

## Son kapı sonuçları

AJA-279 koşusu 24 Kasım 2026 Salı günü yapıldı.

- Ruff biçim denetimi geçti.
- Ruff kural denetiminde tek uyarı kaldı. Uyarı eski `Denied` adının N818 uyarısıdır.
- Modül sınırı kapısı geçti. İhlal sayısı 0'dır.
- Güvenlik kapısı geçti.
- Gateway testleri kap içinde koştu. 75 test geçti. 1 test atlandı.
- Atlanan test gerçek HTTP deneme sitesi ister.
- OpenAPI sözleşme testleri geçti. 6 test koştu.

Gerçek HTTP, şema güncellemesi ve 20 istekli eşzamanlılık testi koşmadı.
Eşzamanlılık testi `concurrency.py` dosyasındadır. Bu test atılabilir deneme sitesi ister.
QA bu testi 8. adımda koşar.

Uzun ve ayırıcısız bir sayı dizisi e-posta desenini yavaşlatır.
Bu sorun taban dalda da vardır. Bu işte değiştirilmedi.

Frappe kaynak kanıtı `frappe/database/query.py` dosyasının 243. ve 270. satırlarıdır.
Sorgunun varsayılanı kayıt izinlerini atlar. Kullanım özeti izinli sorguyu açıkça seçer.

Ruff 0.17.6 gözlendi. Mevcut `Denied` sınıfı N818 ad uyarısı üretir.
Bu eski ad bu işte değiştirilmedi. Hiçbir uyarı kuralı kapatılmadı.
Gerçek okurla denenmedi.
