// Merkezi klavye odak kipi.
// Kip kapalı başlar. Yalnız Tab ve Shift+Tab kipi açar. İşaretçi ve dokunma kipi kapatır.
// Odak göstergeleri atonota.css içinde bu duruma ve :focus-visible koşuluna bağlıdır.
// Bu betik odağı taşımaz, blur() çağırmaz ve hiçbir tuşu engellemez.
(function () {
  var root = document.documentElement;
  root.setAttribute('data-at-js', '');

  document.addEventListener(
    'keydown',
    function (event) {
      if (event.key === 'Tab' && !event.ctrlKey && !event.metaKey) {
        root.setAttribute('data-at-focus', 'keyboard');
      }
    },
    true
  );

  function pointerMode() {
    root.removeAttribute('data-at-focus');
  }

  document.addEventListener('pointerdown', pointerMode, true);
  document.addEventListener('touchstart', pointerMode, { capture: true, passive: true });

  // Açılış kipi (AJA-1293). Koyu tema sınıfını ayrı bir betik ekler. WebKit sayfayı o betikten önce çizer.
  // Geçiş açılışta çalışırsa renkler 200 ms soluk kalır. atonota.css bu işaret gelene kadar geçiş süresini sıfırlar.
  // İşaret "load" olayından iki kare sonra gelir. Böylece koyu tema renkleri geçişsiz çizilmiş olur.
  // Sonraki hover ve odak geçişleri merkezi süre tokenıyla çalışır.
  function motionReady() {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        root.setAttribute('data-at-motion', '');
      });
    });
  }

  if (document.readyState === 'complete') {
    motionReady();
  } else {
    window.addEventListener('load', motionReady, { once: true });
  }
})();
