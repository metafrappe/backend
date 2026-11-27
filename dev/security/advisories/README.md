# Güvenlik danışmanlığı kayıtları

Bu klasör G-142 gereksinimini karşılar.
Güvenlik danışmanlığı, bir yazılımdaki güvenlik açığını duyuran nottur.
Her danışmanlık için bir karar kaydı yazılır.

## Dosyalar

- `sources.json` izlenen kaynakları listeler.
- `template.json` boş karar kaydıdır.
- `records/` klasörü karar kayıtlarını tutar.
- `emergency-patch.md` acil yama yönergesidir.
- `../advisory_records.py` kayıtları denetler.

## İzlenen kaynaklar

`sources.json` şu bileşenleri kapsar:

- Frappe, ERPNext ve HRMS,
- Press ve Press Agent,
- CRM ve Helpdesk,
- Keycloak ve Hocuspocus,
- frontend deposunun npm bağımlılıkları.

Her bileşenin üç tür kaynağı vardır:

1. GitHub güvenlik danışmanlıkları,
2. NVD kayıtları,
3. satıcının sürüm notları.

DevOps sorumlusu bu kaynakları elle denetler.
Zamanlanmış iş kurulmaz.
Yeni bir bileşen kurulursa önce `sources.json` dosyasına ekleyin.

## Karar kaydı yazma

1. `template.json` dosyasını `records/` klasörüne kopyalayın.
2. Dosyaya danışmanlığın kimliğini ad olarak verin. Örneğin `GHSA-abcd-1234-wxyz.json` yazın.
3. Bütün alanları doldurun.
4. Denetimi çalıştırın.

Alanlar şunlardır:

| Alan | Anlamı |
| --- | --- |
| `advisory_id` | Danışmanlık kimliği. Örneğin GHSA ya da CVE numarası. |
| `component` | `sources.json` içindeki bileşen adı. |
| `severity` | Önem düzeyi: `low`, `medium`, `high` ya da `critical`. |
| `known_exploited` | Açık saldırıda kullanılıyorsa `true` yazın. |
| `deployed_version` | Bizde çalışan sürüm. |
| `affected_range` | Açıktan etkilenen sürüm aralığı. |
| `feature_enabled` | Özellik açıksa `yes` yazın. Diğer değerler `no`, `not_installed` ve `unknown` olur. |
| `attack_precondition` | Saldırganın önce sağlaması gereken koşul. |
| `fixed_version` | Açığı kapatan sürüm. Düzeltme yoksa bunu açıkça yazın. |
| `decision` | Karar: `apply_now`, `schedule` ya da `not_applicable`. |
| `rationale` | Kararın gerekçesi. |
| `evidence` | Sürüm ve yapılandırma kanıtı. |
| `decided_by` | Kararı veren rol. |
| `decided_on` | Karar günü. Biçim `2026-11-28` gibidir. |

Kararların anlamı şöyledir:

- `apply_now` hemen uygulanır demektir. Acil yama yönergesi başlar.
- `schedule` sonraki yükseltmeye planlanır demektir.
- `not_applicable` açık bizi etkilemez demektir.

Karar `not_applicable` ise iki kanıt zorunludur.
Örneğin `evidence.version` alanına sürüm komutunun çıktısını yazın.
`evidence.configuration` alanına özelliğin kapalı olduğunu gösteren ayarı yazın.
Kanıta sır, token ya da kişi verisi yazmayın.

## Denetim

Depo kökünde şu komutu çalıştırın:

```sh
python3 -I dev/security/advisory_records.py
```

Kayıtların testi şu komutla koşar:

```sh
python3 -I -m unittest discover -s dev/security -p test_advisories.py
```

Boş zorunlu alan, bilinmeyen karar ve listede olmayan bileşen testi düşürür.
Aynı danışmanlık için iki kayıt da testi düşürür.
