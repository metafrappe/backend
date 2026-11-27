# G-103 arayüz devir notu

Arayüz ekibi bu adımları `atonota-web` deposundaki takip işinde uygular.

1. Girişten sonra [sunucu sözleşmesindeki](../contracts.md#12-uygulama-modülü-listesi-g-103) adresi çağırın.
2. Yanıtın sürümünü ve alanlarını doğrulayın.
3. Her uygulama adını bilinen yükleyici listesinde arayın.
4. Yalnız sunucunun listelediği ve yükleyicisi bulunan paketleri açın.
5. Bir paket yüklenemezse diğer paketlerin açılmasını sürdürün.

Her `@apps/<ad>` paketi `AppModule` arayüzüne uyar.
Bu arayüz, paketin sunduğu parçaların türlerini tanımlar.
Ekran ve yardım kimlikleri sunucu listesindeki kimliklerle eşleşir.

Paket, TanStack Router için ekran yollarını bildirir.
Paket, belge türüne özel ekranları da bildirir.
Paket simgeleri, çevirileri ve gösterge kutularını bildirir.
Paket yardım konularını, tanıtım turunu ve keşif kurallarını bildirir.
Paket hazır yapay zekâ istemlerini ve araç adlarını bildirir.

Renk, yazı, boşluk ve hareket için `@platform/design-tokens` paketini kullanın.
Örneğin bir düğme, ortak ana eylem rengini kullanır.

Otomatik testte kurulu bir uygulamanın açıldığını doğrulayın.
Kurulu olmayan bir uygulamanın kodunun indirilmediğini doğrulayın.
Bilinmeyen uygulama adında arayüzün çalışmaya devam ettiğini doğrulayın.
TypeScript ve paket sözleşme testini birleştirme denetimine ekleyin.

Bu işteki yerel testler sunucu sözleşmesini kapsar.
Arayüz paketi ve gerçek tarayıcı denetimi takip işine aittir.
