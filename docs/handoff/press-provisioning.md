# Press ile sunucu kurma

## Kapsam ve görev sahibi

Bu not hazırlık ortamındaki Press işini anlatır.
Kapsanan gereksinimler G-1, G-3, G-4, G-6 ve G-55'tir.
Görev sahibi DevOps sorumlusudur. Press uygulama ekibi kurulum akışına destek verir.

Press'in sunucu kurma adımları tek yerde yazılıdır. Bu yer [Press sunucu kurulumu devir notudur](../../dev/press/provisioning-handoff.md). O not yerel denemenin sonucunu da anlatır. Bu not o adımları tekrar etmez.

## Bağımlılıklar

- [Hazırlık sunucusu](staging-server.md) çalışmalıdır.
- DevOps sorumlusu deneme sunucularına ve paket deposuna erişebilmelidir.
- Yedek deposu ve boş kurtarma veritabanı hazır olmalıdır.
- Press sürüm farkı kayda alınmalıdır. Bu işi DevOps sorumlusu ve Press uygulama ekibi yapar.

## Adımlar

1. Yayın hedefini proje kaydıyla karşılaştırın. Eski hedef Frappe 15 ve Python 3.11 idi. O-9 ve O-52 kararları Frappe 16 ile Python 3.14 kullanır.
2. Denenecek Press sürümünü ve commit kodunu kaydedin. O-52 kararı Press v0.154.1 için beş uyum yaması tanımlar. Yamalar `deploy/images/press-patches/` klasöründedir.
3. [Press imajı belgesine](../dagitim/press-imaji.md) göre paketi derleyin.
4. Press'e sunucu kayıtlarını ekleyin. Kayıt listesi aşağıdadır.
5. Press temel ayarlarını tamamlayın. Ayar listesi aşağıdadır.
6. Deneme sunucusunu Press ile kurun. Adımlar [Press sunucu kurulumu devir notundadır](../../dev/press/provisioning-handoff.md).
7. Derlenen uygulama paketini Registry adlı paket deposuna yükleyin.
8. Yüklenen paketten bir test sitesi açın.
9. Ağ ve erişim kontrollerini hazırlık ortamında uygulayın.
10. MariaDB ayarlarını Press'teki Database Server kaydına uygulayın.
11. İşlem günlüğünün yedek deposuna aktarıldığını doğrulayın.
12. Son bir saatin işlemlerini ayrı test veritabanına geri yükleyin.

### Sunucu kayıtları ve Press ayarları

- Proxy, uygulama, derleme ve veritabanı sunucularını kaydedin. Paket deposu, izleme ve günlük sunucularını kaydedin. Yeni siteler için uygulama sunucusunu seçin. Derleme sunucusu x86_64 olmalıdır.
- Fiziksel sunucuları `Generic` kümesine alın. Hetzner Cloud sunucularını `Hetzner` kümesine alın.
- Alan adı, küme, paket deposu adresi ve ad alanını kaydedin.
- Derleme, izleme ve günlük sunucularını seçin.
- Sertifika dizini, kayıt e-postası ve RSA anahtar boyutunu belirleyin.
- Anlık iş bildirimini açın. Hazır site havuzunu ayarlayın. Sertifika yenileme kuyruğunun boyutunu belirleyin.
- Telegram ve e-posta bildirim alıcılarını doğrulayın.
- Google OAuth ve ön e-posta doğrulamasını kapatın. Tek kullanımlık e-postayı engelleyin. Deneme sitesi sınırını 1 yapın.
- Yeni çalışma grupları için `bench_configuration` varsayılanını kontrol edin.

### Ağ ve veritabanı

- Press ağ kurulumunda özel ağı ve güvenlik duvarını etkinleştirin.
- SSH erişimini özel ağ ve yetkili sertifikalarla sınırlayın.
- Başarısız giriş korumasını ve sistem denetim günlüğünü açın.
- MariaDB bellek ve bağlantı sınırlarını sunucu kapasitesine göre ayarlayın.
- Fiziksel yedeği ve işlem günlüğü dizinini etkinleştirin.
- İşlem günlüğü saklama süresini Press kaydına yazın.
- Felaket kurtarma için veritabanının ikinci kopyasını doğrulayın.

## Doğrulama

- **G-1.** Hazırlık ortamında `bench migrate` ile veri güncellemesini deneyin. Etkinleştirme testini çalıştırın. Yama ve sürüm farkını sonuçla birlikte kaydedin.
- **G-3.** Press sunucu kayıtlarını kontrol edin. Paket kodunu ve test sitesinin açılışını kaydedin.
- **G-4.** Press Settings ayarlarını ve bildirim teslimini kontrol edin. Yeni çalışma grubunun varsayılanlarını doğrulayın.
- **G-6.** Özel ağdan operatör erişimini doğrulayın. Açık internetten operatör erişiminin engellendiğini kontrol edin. Panelin Press ve Socket.IO yollarını doğrulayın. Güvenlik duvarı kayıtlarını inceleyin.
- **G-55.** `SHOW GLOBAL VARIABLES;` çıktısını Press değerleriyle karşılaştırın. Bellek, bağlantı ve denetim ayarlarını kontrol edin. Yazma günlüğünün 365 gün saklandığını doğrulayın. Yedek deposundaki işlem günlüğünden son 1 saati kurtarın. Beklenen test kayıtlarını kurtarılan kayıtlarla karşılaştırın.

## Kabul ölçütü

Press, Frappe 16 üzerinde bir hazırlık sunucusu kurar. DevOps sorumlusu test sitesinin paket deposundan açıldığını gösterir.
Sürüm farkı kayıtla çözülür. DevOps sorumlusu beş gereksinimin doğrulama sonuçlarını kaydeder.
Press'in canlıya çıkış engeli O-9 kararındadır. Bu engel, hazırlıkta sunucu kurma akışı geçince kapanır.

- [Proje kaydı](../../PROJECT-RECORD.md)
- [Press uygulama notu](../tasks/press-tr.md)
