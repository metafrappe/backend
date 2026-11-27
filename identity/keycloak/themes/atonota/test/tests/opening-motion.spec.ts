import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { screen, screens } from './helpers';

// AJA-1293. Koyu tema sınıfını bir betik sayfa çizildikten sonra ekler. WebKit bu betiği beklemez.
// Renk geçişi açılışta da çalışırsa renkler önce açık temayla çizilir ve 200 ms soluk kalır.
// Bu dosya renklerin açılışta son değerinde olduğunu ve geçişin yalnız etkileşimde çalıştığını denetler.

const tags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

/** Şu anda çalışan CSS geçişlerini listeler. Öğe ve özellik adıyla döner. */
const runningTransitions = (page: Page) =>
  page.evaluate(() =>
    document
      .getAnimations()
      .filter((animation) => animation.constructor.name === 'CSSTransition')
      .map((animation) => {
        const target = (animation.effect as KeyframeEffect | null)?.target as Element | null;
        const property = (animation as unknown as { transitionProperty: string }).transitionProperty;
        return `${target?.tagName.toLowerCase()}#${target?.id}.${String(target?.className).slice(0, 40)} ${property}`;
      }),
  );

/** Ana düğmenin geçiş süresi. Sayfa açılışı bitince merkezi tokena (200 ms) döner. */
const primaryDuration = (page: Page) =>
  page.locator('#kc-login').evaluate((element) => getComputedStyle(element).transitionDuration);

/** Ekrana yalnız adresle gelinir. Kullanıcı form göndermez. Bu ekranlarda açılışta hiç geçiş çalışmamalıdır. */
const openedOnly = new Set(['sign-in', 'register', 'password-reset']);

for (const scheme of ['dark', 'light'] as const) {
  for (const item of scheme === 'dark' ? screens : [screen('sign-in')]) {
    test(`${item.name}: açılışta renk geçişi yok, axe beklemeden temiz (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await item.open(page);
      if (scheme === 'dark') await expect(page.locator('html')).toHaveClass(/pf-v5-theme-dark/);
      // Bilerek beklenmez. Renkler sayfa açılır açılmaz son değerinde olmalıdır.
      // Form gönderen ekranlarda geçişi kullanıcının işlemi başlatır. O geçiş doğrudur, burada sayılmaz.
      if (openedOnly.has(item.name)) expect(await runningTransitions(page), 'açılışta çalışan geçiş').toEqual([]);
      const results = await new AxeBuilder({ page }).withTags(tags).analyze();
      const summary = results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`);
      expect(summary).toEqual([]);
    });
  }
}

for (const selector of ['#at-forgot-password', '#authenticateWebAuthnButton']) {
  test(`açılıştan sonra ${selector} hover geçişi iki yönde 200 ms tokenıyla çalışır (koyu)`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await screen('sign-in').open(page);
    await expect(page.locator('html')).toHaveClass(/pf-v5-theme-dark/);
    await expect.poll(() => primaryDuration(page), 'açılış bitince geçiş açılır').toBe('0.2s, 0.2s, 0.2s');
    const target = page.locator(selector);
    const transitionsOn = () =>
      target.evaluate((element) =>
        element
          .getAnimations()
          .filter((animation) => animation.constructor.name === 'CSSTransition')
          .map((animation) => (animation.effect as KeyframeEffect).getTiming().duration),
      );
    await target.hover();
    expect(await transitionsOn(), 'üzerine gelince').toContain(200);
    // Yarıda geri dönen geçişin süresi kısalır. Bu yüzden önce ilk geçişin bitmesi beklenir.
    await target.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished)));
    await page.mouse.move(0, 0);
    expect(await transitionsOn(), 'üzerinden ayrılınca').toContain(200);
  });
}

test('açılıştan sonra odak ve hover kurallarının geçişi merkezi tokendadır', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await screen('sign-in').open(page);
  await expect.poll(() => primaryDuration(page)).toBe('0.2s, 0.2s, 0.2s');
  const durations = await page.evaluate(() =>
    ['#kc-login', '.pf-v5-c-form-control:has(#username)', '#at-forgot-password'].map((selector) => {
      const element = document.querySelector(selector);
      return `${selector} ${element ? getComputedStyle(element).transitionDuration : 'yok'}`;
    }),
  );
  expect(durations).toEqual(['#kc-login 0.2s, 0.2s, 0.2s', '.pf-v5-c-form-control:has(#username) 0.2s', '#at-forgot-password 0.2s']);
});

test('azaltılmış hareket tercihinde açılıştan sonra da hover geçişi çalışmaz', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
  await screen('sign-in').open(page);
  await page.waitForLoadState('load');
  // Açılış kipinin kapanması için iki kare beklenir. Sonra süre yine sıfır kalmalıdır.
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.locator('#at-forgot-password').hover();
  expect(await runningTransitions(page)).toEqual([]);
  expect(Number.parseFloat(await primaryDuration(page))).toBe(0);
});
