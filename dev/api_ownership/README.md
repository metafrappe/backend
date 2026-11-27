# API sahiplik kaydı (G-126)

Her API ucunun bir sahip kaydı vardır.
Kayıt `contracts/api-ownership.json` dosyasındadır.

## Kayıtta ne yazar

Her kayıt bir uçtur. Kayıtta şu alanlar bulunur:

- `endpoint` alanı ucun adını tutar. Örneğin `platform_core.api.access.get_rules`.
- `app` ve `file` alanları ucun uygulamasını ve dosyasını tutar.
- `owner_team` alanı sahip işi tutar. Ad `AGENTS.md` içindeki klasör tablosundan gelir.
- `status` alanı üç değerden birini alır: `upstream-ready`, `new-custom`, `upstream-patch`.
- `version` alanı ucun sürümünü tutar. Biçim `1.2.3` şeklindedir.
- `methods` ve `access` alanları koddaki `frappe.whitelist` ayarıyla aynı olur.

`overrides` bölümü `override_whitelisted_methods` satırlarını tutar.
Bu satırlarda `target` alanı bizim fonksiyonumuzu gösterir.

## Denetim

Denetim kodu tarar ve kayıtla karşılaştırır.
Şu durumlarda denetim düşer:

1. Kodda bir uç var ama kayıtta yok.
2. Kayıtta bir uç var ama kodda yok.
3. Kayıtta sahip takım ya da sürüm boş.
4. Kayıttaki dosya, yöntem ya da erişim kodla uyuşmuyor.

Yeni uç ekleyen kişi kayda da bir satır ekler.

Denetimi depo kökünden şu komutla koşun:

```bash
python3.14 -I backend/dev/api_ownership/registry_check.py backend
```

Denetimin testleri şu komutla koşar:

```bash
python3.14 -I -m unittest discover -s backend/dev/api_ownership
```

Kodda Python 3.12 sözdizimi var. Bu yüzden Python 3.9 ile tarama hata verir.
`backend/dev/tests/test_api_ownership_registry.py` aynı denetimi gerçek kodda koşar.
