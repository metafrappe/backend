# G-37 yedekleme hizmet sözü

Bu belge yedekleme hizmet sözünü yazar. Hizmet sözüne SLA da denir.
Değerler karar sitesindeki G-37 gereksiniminden gelir.
`deploy/tests/test_backup_sla.py` testi tablodaki değerleri denetler.
Test, araçların aynı değerleri uyguladığını da denetler.

## Değerler

| Anahtar | Değer | Anlamı |
| --- | --- | --- |
| `rpo_hours` | 24 | En çok 24 saatlik veri kaybedilebilir. |
| `restore_report_interval_months` | 1 | Geri yükleme deneme raporu her ay hazırlanır. |
| `full_restore_interval_months` | 3 | Her 3 ayda bir kiracının yedeği yeni bench'e tam yüklenir. |
| `archive_retention_months` | 6 | Arşivlenen sitenin yedeği en az 6 takvim ayı saklanır. |
| `export_parts` | database, public, private | Müşteri bu üç yedek parçasını indirir. |

RPO, kaybedilebilecek en uzun veri aralığıdır.
Bench, Frappe sitelerini çalıştıran klasör ve araç düzenidir.

## Değerleri uygulayan araçlar

- `deploy/backup_export.py` veri yaşını 24 saatle sınırlar.
- Aynı araç saklama süresini 6 takvim ayı olarak hesaplar.
- Aynı araç müşterinin şifreli yedeğini indirir. Ayrıntı [dışa aktarım sözleşmesindedir](backup-export.md).
- `deploy/restore_drill.py` yerel yığında geri yükleme denemesi yapar.

## Yerel geri yükleme denemesi

Deneme yerel bir siteye işaret notu yazar.
Sonra siteyi dosyalarıyla birlikte yedekler.
Yedeği yeni ve geçici bir siteye yükler.
İki sitedeki kayıt sayılarını karşılaştırır. İşaret notunu yeni sitede arar.
Sonunda geçici siteyi, yedeği ve işaret notunu siler.
Son yerel denemenin sonucu `docs/evidence/g37-restore-drill.json` dosyasındadır.

Araç yalnız `tenant1.localhost` ve `test-*.localhost` sitelerini kabul eder.
Araç sunucuya bağlanmaz. Araç zamanlanmış iş kurmaz.

## Açık kalan sunucu işi

Yerel deneme sunucudaki yedeğin kanıtı değildir.
Aylık rapor ve 3 aylık tam dönüş sunucuda yapılır.
Bu işler [sunucu devir notundadır](../handoff/backup-restore.md) (`docs/handoff/backup-restore.md`).
G-37, sunucu kanıtları gelmeden tamamen kapanmaz.
