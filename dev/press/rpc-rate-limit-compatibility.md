# Press RPC istek sınırı kararı

Press deneme ortamı Frappe v16.56.0 ve Press v0.154.1 kullanır.
Canlı Press imajı da Frappe 16.56.0 kullanır.

Frappe 16.56.0 istek sınırı sayacını işlev adından üretir.
Bu yüzden Press bu sürümde geçici sayaç adı kullanmaz.
API v1 ve API v2 çağrıları aynı sayacı paylaşır.

Daha eski Frappe 16 sürümleri sayacı `frappe.form_dict.cmd` alanından adlandırır.
API v2 bu alanı doldurmaz.
`press_tr.api.rate_limit_namespace` bu sürümler için geçici bir ad yazar.
Yerel test, Frappe 16.56 kolunda `cmd` alanının değişmediğini doğrular.

[Frappe 16.56.0 kaynak kodu](https://github.com/frappe/frappe/blob/v16.56.0/frappe/rate_limiter.py)
