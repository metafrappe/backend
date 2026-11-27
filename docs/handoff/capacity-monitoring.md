# Kapasite ölçümü ve izleme

Bu not işçi sayısının ölçümle seçilmesini ve izlemenin kurulmasını anlatır. Not 23 Kasım 2026 Pazartesi günü yazıldı. Not 28 Kasım 2026 Cumartesi günü bu depoya taşındı. Bilgiler aynı gün `main` dalıyla karşılaştırıldı.

## Kapsam

- Bu not denetim raporunun 5. bölümündeki 20. işi kapsar.
- Bu iş [proje kaydındaki](../../PROJECT-RECORD.md) iki teknik borcu kapatır.
- Birinci borç şudur: Üretim işçi sayısı ölçülmedi.
- İkinci borç şudur: Performans ölçümü yalnız elle yapılır (O-31).
- Gereksinimler G-50 ve G-113'tür. G-149 ölçüm yöntemini verir.

İşçi, istekleri ve arka plan işlerini yürüten süreçtir. Kuyruk, sırasını bekleyen arka plan işlerinin listesidir.

## Görev sahibi

- Görev sahibi Hüseyin Cengiz'dir.
- Platform ekibi ve Frontend ekibi gerçek kullanıcı ölçümünü kurar.

## Adımlar

1. Hüseyin Cengiz G-50 başlangıç değerlerini hazırlık sunucusuna yazar. Değerler ve denetim betiği [g50-worker-sizing.md](g50-worker-sizing.md) notundadır.
2. Başlangıçta web işçisi en az 2, en çok 8 olur.
3. Başlangıçta arka plan işçisi en az 2, en çok 6 olur.
4. Hüseyin Cengiz uzun iş kuyruğunun süre sınırını 3000 saniye yapar.
5. Hüseyin Cengiz `reports` kuyruğunu açar.
6. Hüseyin Cengiz her yeni sitede zamanlayıcının açık olduğunu doğrular.
7. Hüseyin Cengiz Prometheus ve Grafana izleme sunucusunu kurar.
8. Hüseyin Cengiz günlük sunucusunu kurar.
9. Hüseyin Cengiz hata izleme servisini kurar. Servis kendi sunucumuzdaki GlitchTip olur.
10. Hüseyin Cengiz hata kayıtlarından kişisel bilgiyi temizleyen ayarı açar.
11. Hüseyin Cengiz dışarıdan çalışma denetimi kurar.
12. Platform ekibi gerçek kullanıcı ölçümünü kendi toplayıcımıza bağlar. Üçüncü taraf ölçüm aracı kullanılmaz.
13. Hüseyin Cengiz gerçek kullanıcı yolculuklarından k6 yük denemesi hazırlar.
14. Hüseyin Cengiz yük denemesini hazırlık sunucusunda çalıştırır.
15. Hüseyin Cengiz işçi sayısını ölçüm sonucuna göre seçer.
16. Hüseyin Cengiz bir örnek hata üretir. Hatanın doğru alıcıya ulaştığını görür.
17. Hüseyin Cengiz kapasite ve maliyet kaydını yazar.

Bu not zamanlanmış iş kurmaz. Yük denemesini bir kişi elle başlatır.

## Bağımlılıklar

- Hazırlık sunucusu kurulmuş olmalı. Ayrıntı [staging-e2e.md](staging-e2e.md) dosyasındadır.
- Uçtan uca sınama geçmiş olmalı. Yük denemesi bu akışları kullanır.
- Hata izleme servisinin adresi sunucudaki sır dosyasında durur. Adres depoya yazılmaz.

## Doğrulama

1. Grafana'da web isteği süresi p75 ve p95 değerleriyle görünür.
2. Grafana'da kuyruk bekleme süresi görünür.
3. Örnek hata hata izleme ekranında görünür.
4. Örnek hatada e-posta ve ad gibi kişisel bilgi görünmez.
5. Yük denemesi raporunda kullanıcı sayısı, süre ve hata oranı yazar.

## Kabul ölçütü

- İşçi sayısı yük ölçümüyle seçildi. Ölçüm raporu var.
- Yeni sitede zamanlayıcı açık.
- Kuyruklar ve uzun işler belirtilen sınırlarla sınandı.
- Örnek hata izleme ekranına ve doğru alıcıya ulaştı.
- Hata kayıtlarında kişisel bilgi yok.
- Kapasite ve maliyet kaydı var.
- İki borç proje kaydının teknik borç tablosundan çıktı.

Yük denemesindeki sayılar ürün sözü değildir. Bu sayılar ölçülmüş kapasiteyi gösterir.
