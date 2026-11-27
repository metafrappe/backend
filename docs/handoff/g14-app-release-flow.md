# G-14: uygulama yayımlama akışı, canlı Press adımları

Bu not G-14 işinin canlı Press adımlarını anlatır. İş kaydı AJA-2371 numaralıdır.

Kurallar kod olarak `apps/press_tr/press_tr/app_release.py` dosyasındadır. Testler `apps/press_tr/tests/test_app_release.py` dosyasındadır. Kod Press kayıtlarını değiştirmez. Aşağıdaki adımları bir kişi Press panelinde uygular.

## Görev sahibi

Adımları Hüseyin Cengiz uygular. Hüseyin Cengiz sonucu da doğrular. Bu adımlarda alan adı ve DNS işi yoktur. Bu yüzden Asistan Hüseyin bu işte görev almaz.

## Durum

Bu adımlar canlıda uygulanmadı. Yerelde yalnız birim testleri koştu. Canlı doğrulamanın durumu `not_run` olur.

## Kod tanımları

Kodda üç uygulama kaynağı vardır:

- `frappe`, kaynak `https://github.com/frappe/frappe`, dal `version-16`.
- `erpnext`, kaynak `https://github.com/frappe/erpnext`, dal `version-16`.
- `hrms`, kaynak `https://github.com/frappe/hrms`, dal `version-16`.

Kodda iki Release Group vardır. Release Group, aynı uygulamaları taşıyan sunucu grubudur.

- `erpnext-v16-tr-staging` deneme grubudur. Bu grupta otomatik dağıtım açıktır.
- `erpnext-v16-tr-prod` canlı gruptur. Bu grupta otomatik dağıtım kapalıdır. Dağıtım yalnız zamanlanmış dağıtımla olur.

Bakım saatleri sunucu saatiyle (UTC) şunlardır:

- 01:00 ile 05:59 arası.
- 21:00 ile 23:59 arası.

Bu saatler Press `hooks.py` dosyasındaki `deploy_hours` değeriyle aynıdır. Türkiye saatinde 04:00 ile 08:59 arası ve 00:00 ile 02:59 arasıdır.

Her uygulamanın `pyproject.toml` dosyası şu satırı taşır:

```toml
[tool.bench.frappe-dependencies]
frappe = ">=16.0.0,<17.0.0"
```

Alt sınır 16 sürümünün içinde yükselebilir. Örneğin `>=16.56.0,<17.0.0` kabul edilir. Üst sınır her zaman `<17.0.0` olur. Bu satırı taşımayan uygulama reddedilir.

## Canlı adımlar

1. Hüseyin Cengiz Press panelinde her uygulama için App kaydını açar.
2. Hüseyin Cengiz her uygulamaya App Source kaydı ekler. Kaynak adresi ve dal yukarıdaki listeyle aynı olur. GitHub App bağlantısını Press panelinden kurar.
3. Hüseyin Cengiz `erpnext-v16-tr-staging` grubunu kurar. Gruba üç uygulamayı ekler. “Enable Auto Deploy” kutusunu işaretler.
4. Hüseyin Cengiz `erpnext-v16-tr-prod` grubunu kurar. Gruba aynı üç uygulamayı ekler. “Enable Auto Deploy” kutusunu boş bırakır.
5. Hüseyin Cengiz “Scheduled Deploy Settings” kaydını açar. “Groups” tablosuna yalnız `erpnext-v16-tr-prod` grubunu ekler.
6. Canlı sitelerde müşteri isterse güncelleme saati seçilir. Hüseyin Cengiz bunun için site ayarındaki `only_update_at_specified_time` ve `update_trigger_time` alanlarını kullanır. Seçilen saat bakım saatlerinin içinde olur.

## Doğrulama

Hüseyin Cengiz şu sonuçları görür ve kayda yazar:

1. Deneme grubunda yeni commit gelince dağıtım kendiliğinden başlar.
2. Canlı grupta dağıtım bakım saati dışında başlamaz.
3. Canlı grupta dağıtım bakım saati içinde başlar.
4. Listede olmayan bir kaynak eklenmek istenirse işlem durur. Örneğin başka bir GitHub deposu eklenirse kişi kaydı geri alır.

## Açık uç

Kod şimdilik Press kayıtlarına bağlı değildir. Press bir kaydı kaydederken bu kurallar kendiliğinden çalışmaz. Kuralları Press'e bağlamak ayrı bir iştir. O işte `hooks.py` dosyasına kayıt olayı eklenir.

Projenin kendi uygulamaları bu listede yoktur. Bunlar `hrms_tr`, `platform_core` ve `press_tr` uygulamalarıdır. Bu uygulamalar bugün tek depodadır. Her biri ayrı depoya taşınınca kaynak listesine eklenir. Bugün test bu uygulamaların `pyproject.toml` dosyalarını denetler.
