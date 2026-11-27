# Hazır kayıt temizliğini doğrulayın

Bu iş G-8 gereksinimidir. Git dalı `pc/g7-g8-press-cleanup` adını taşır.

Frappe güncelleme sırasında önce Press'in hazır kayıtlarını yükler. Hazır kayda fixture denir. Sonra Frappe `after_migrate` listesindeki işleri çalıştırır. Bu listede `press_tr.fixture_cleanup.disable_cloud_defaults` işi vardır. Temizlik yalnız iki Team Tier kaydını siler. Bu kayıtlar Power ve Elite kayıtlarıdır. Öteki kayıtlarda temizlik yalnız alan değerini değiştirir.

## Temizliğin yaptığı işler

1. Temizlik Press dosyasındaki 686 Site Plan kaydını kapatır.
2. Press dosyasında olmayan planlar bizimdir. Temizlik bu planları açık bırakır.
3. Temizlik `press.signup_e2e.run_signup_e2e` işini durdurur.
4. Temizlik Team Tier değerlerini karar tablosuna eşitler.
5. Temizlik Power ve Elite düzeylerini siler.
6. Bölge listesi varsa temizlik kullanılmayan Cluster kaydını gizler.
7. Aynı durumda temizlik bu Cluster kaydına bağlı Server Plan kaydını kapatır.

Cloud Region kaydında açma ve kapatma alanı yoktur. Temizlik bu kayda dokunmaz.

## Team Tier karar tablosu

Orkestratör bu tabloya 24 Kasım 2026 Salı günü karar verdi. Proje sahibi kararı orkestratöre bıraktı. Orkestratör koşulları 25 Kasım 2026 Çarşamba günü düzeltti. Artık tablo yalnız Press'in sınadığı koşulları yazar. Karar sonradan değişebilir. Değerler dolardır.

| Düzey | Koşul | Aylık harcama sınırı |
| --- | --- | --- |
| Beginner | Kart yok | 0 dolar |
| Growth | Kart eklendi | 1.000 dolar |
| Intermediate | Son fatura en az 400 dolar | 2.500 dolar |
| Advance | Son fatura en az 750 dolar | 10.000 dolar |

Press düzeyi yükseltmeden önce 3 ödenmiş fatura da ister. Bu kural Press'in kendi kuralıdır. Tablo bu kuralı değiştirmez.

Tabloda `paying_user_since` alanı her düzeyde 0 olur. Press v0.154.1 bu alanı hiçbir kuralda sınamaz. Press'in hazır kaydı bu alana başka sayılar yazar. Örneğin Growth için 3 yazar. Press ödeme ekranı bu sayıyı müşteriye koşul gibi gösterir. Biz alanı 0 yazarız. Böylece müşteri sınanmayan bir koşul görmez.

Power ve Elite düzeyleri kapalıdır. Kurumsal müşterinin sınırını bir insan elle yazar.

Tablo yalnız bir yerde durur. Bu yer `press_tr/fixture_cleanup.py` dosyasındaki `DEFAULT_TEAM_TIERS` değeridir. `press_tr_team_tiers` site ayarı yazılırsa ayar bu tablonun yerine geçer.

Bir Team kaydı Power ya da Elite düzeyindeyse temizlik hata verir. Bu durumda hiçbir Team Tier kaydı değişmez. O Team kaydını önce başka düzeye taşıyın.

## Press kurallarıyla çelişen koşullar

Bu notlar Press v0.154.1 sürümünün kodundan çıkarıldı.

1. Press yeni ekibe 100 dolar sınır yazar. Press Beginner tutarını burada okumaz.
2. Düzey değişince Press `amount or 100` kuralını kullanır. Bu yüzden 0 dolar 100 dolar olur.
3. 100 dolar sınır da ücretli planı engeller. En ucuz ücretli plan 400 dolardır.
4. Sınır gerçekten 0 olsaydı Press deneme sitesini de engellerdi. Press `sınır <= toplam` denetimi yapar. 0 dolar 0 dolara eşittir.
5. Press düzeyi `update_team_tier` kuralıyla yükseltir. Kural 3 ödenmiş fatura ister. Kural yalnız son fatura tutarına bakar.
6. Kural `paying_user_since` alanını okumaz. Bu yüzden tablo bu alana 0 yazar.
7. Beginner ve Growth düzeylerinde son fatura eşiği 0 dolardır. Press iki düzeyi bu eşikle sıralar. Ekip 400 dolardan az öderse Press Beginner düzeyini seçebilir.

Bu çelişkiler için Press'e yama yazılmadı. Karar ürün sahibinindir.

## İnsan kararı bekleyen değerler

Bir değer yalnız site ayarından okunur. Değer yoksa ilgili adım hiçbir şeyi değiştirmez.

- `press_tr_enabled_clusters` ayarı kullanılan Cluster adlarının listesidir. Altyapı sorumlusu bu listeyi verir.

Site ayarındaki Team Tier tablosu açık her Press Team Tier kaydını bir kez içermelidir. Her satırda `amount` ve `last_invoice_amount` alanı olmalıdır. `paying_user_since` alanı isteğe bağlıdır. Değerler sıfır ya da daha büyük sayı olmalıdır. Tablo eksikse temizlik hata verir ve hiçbir Team Tier kaydını değiştirmez.

Press, Team Tier `amount` değerini ekibin harcama sınırı yapar. Press bu sınırı dolar fiyatıyla karşılaştırır. Bu yüzden tablodaki tutarlar dolar karşılığıdır.

Listede Cluster olmayan bir ad varsa temizlik hata verir. Bu durumda hiçbir Cluster kaydı değişmez.

Temizlik yalnız kapatır. Bir ad listeden sonra çıkarılırsa Cluster kendiliğinden açılmaz. Bu Cluster kaydını yönetim ekranında elle açın.

Ayar yanlışsa `bench migrate` komutu durur. Bu bilinçli bir seçimdir. Yanlış fiyat ya da bölge Press kayıtlarına yazılmamalıdır. Press yeni bir Team Tier eklerse tabloya ya da kapalı düzey listesine eklenmelidir. Eklenmezse güncelleme durur.

Cluster kaydını gizleme yöntemi mimar onayı ister. SAFe System Architect bu öneriyi onaylamalıdır.

## Ayrı deneme sitesinde yapılacaklar

1. Dalı ayrı bir Press deneme sitesine kurun.
2. Press'in `site_plan.json` dosyasında 686 kayıt olduğunu doğrulayın.
3. Deneme sitesine ayrı adlı bir yerel plan ekleyin.
4. Deneme sitesinde `bench --site <test-site> migrate` komutunu çalıştırın.
5. Hazır planların `enabled=0` olduğunu doğrulayın.
6. Yerel planın açık kaldığını doğrulayın.
7. `press.signup_e2e.run_signup_e2e` işinde `stopped=1` olduğunu doğrulayın.
8. Aynı güncellemeyi yeniden çalıştırın.
9. Plan ve iş sayılarının aynı kaldığını doğrulayın.

10. Team Tier değerlerinin karar tablosuna eşit olduğunu doğrulayın.
11. Power ve Elite kayıtlarının olmadığını doğrulayın.

Bölge listesi gelince üç adım daha yapın:

1. Listeyi deneme sitesinin ayarına yazın.
2. Güncellemeyi yeniden çalıştırın.
3. Cluster ve Server Plan değerlerini doğrulayın.

Canlı sunucuda ve çalışan 7400 ortamında veri güncellemesi yapılmadı.
