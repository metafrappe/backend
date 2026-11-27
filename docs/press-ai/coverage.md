# press-ai kapsam tablosu

Bu tablo `tools/press-ai` paketinin işlem kapsamını gösterir.
Tabloyu elle düzenlemeyin.
Tabloyu şu komut üretir:

```sh
python3 -I tools/press-ai/server.py coverage-markdown
```

Kontrat değişince komutu çalıştırın. Sonra işaretler arasındaki bloğu çıktıyla değiştirin.
Tablonun güncel olduğunu şu komut denetler:

```sh
python3 -I tools/press-ai/server.py coverage-markdown --check docs/press-ai/coverage.md
```

Birim testi de aynı karşılaştırmayı yapar.
Canlı Press doğrulaması yapılmadı. Durumu `not_run` olarak kalır.

<!-- press-ai:coverage:start -->

| Aile | uygulandı | salt okuma | planlı | desteklenmez | uygulanamaz | bilinmiyor | Toplam |
| --- | --- | --- | --- | --- | --- | --- | --- |
| App, Source, Release Group | 7 | 0 | 6 | 0 | 0 | 0 | 13 |
| Candidate, build, deploy | 8 | 0 | 1 | 1 | 0 | 0 | 10 |
| Bench ve site | 7 | 2 | 2 | 0 | 0 | 0 | 11 |
| İşler ve teşhis | 4 | 0 | 3 | 1 | 0 | 0 | 8 |
| Yedek | 2 | 0 | 1 | 1 | 0 | 0 | 4 |
| Sunucu ve altyapı | 2 | 0 | 0 | 7 | 0 | 0 | 9 |
| Erişim ve ayarlar | 2 | 0 | 1 | 2 | 0 | 0 | 5 |
| Uygulama geliştirme | 11 | 0 | 3 | 3 | 0 | 0 | 17 |
| **Toplam** | 43 | 2 | 17 | 15 | 0 | 0 | **77** |

Kılavuzun 67 adımı, adımdaki en zayıf işlemin statüsüne göre: 36 uygulandı, 2 salt okuma, 19 planlı, 10 desteklenmez. En az bir işlemi uygulanmış adım: 60. Canlı Press doğrulaması: `not_run`.

<!-- press-ai:coverage:end -->
