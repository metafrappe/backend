import { randomUUID } from 'node:crypto';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { BRAND, openLogin, screen, submitPassword } from './helpers';

// G-80, G-132 and G-145: real Keycloak pages, with made-up inputs only.
// Application routes, saved filters and print previews belong to atonota-web.

async function tabTo(page: Page, target: Locator, browserName: string): Promise<void> {
  const key = browserName === 'webkit' ? 'Alt+Tab' : 'Tab';
  for (let step = 0; step < 20; step += 1) {
    await page.keyboard.press(key);
    if (await target.evaluate((element) => element === document.activeElement)) break;
  }
  await expect(target).toBeFocused();
}

async function expectReadablePage(page: Page): Promise<void> {
  await expect(page.locator('.at-brand')).toContainText(BRAND);
  const metrics = await page.evaluate(() => {
    const smallText: string[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const element = node.parentElement;
      if (!node.textContent?.trim() || !element || element.closest('script, style')) continue;
      const style = getComputedStyle(element);
      const range = document.createRange();
      range.selectNodeContents(node);
      if (!range.getClientRects().length || style.visibility === 'hidden') continue;
      if (Number.parseFloat(style.fontSize) < 14) smallText.push(element.tagName);
    }
    for (const element of document.querySelectorAll('input, button, textarea')) {
      if (element.getClientRects().length && Number.parseFloat(getComputedStyle(element).fontSize) < 14) {
        smallText.push(element.tagName);
      }
    }
    return {
      width: window.innerWidth,
      pageWidth: document.documentElement.scrollWidth,
      smallText,
    };
  });
  expect(metrics.pageWidth, 'the page must not scroll horizontally').toBeLessThanOrEqual(metrics.width);
  expect(metrics.smallText, 'visible text must be at least 14 CSS px').toEqual([]);
}

async function expectPrivateAddresses(page: Page, navigations: string[], values: string[]): Promise<void> {
  const addresses = await page.locator('a[href], form[action]').evaluateAll((elements) =>
    elements.map((element) => element.getAttribute('href') ?? element.getAttribute('action') ?? ''),
  );
  expect(navigations.length, 'the test must observe a real navigation').toBeGreaterThan(0);
  for (const address of [...navigations, page.url(), ...addresses]) {
    // Decode twice to catch both ordinary query encoding and an encoded nested redirect.
    let decoded = address;
    for (let pass = 0; pass < 2; pass += 1) decoded = decodeURIComponent(decoded.replace(/\+/g, ' '));
    for (const value of values) {
      expect(decoded.includes(value), 'personal input must not appear in a browser address or link').toBe(false);
    }
  }
}

test('G-80: keyboard opens and leaves the Turkish recovery screen without a focus ring', async ({ page, browser, browserName }, testInfo) => {
  await openLogin(page, 'tr');
  await testInfo.attach('environment', {
    body: JSON.stringify({
      browser: browserName,
      version: browser.version(),
      platform: process.platform,
      architecture: process.arch,
      viewport: page.viewportSize(),
      input: 'keyboard',
    }),
    contentType: 'application/json',
  });
  await expectReadablePage(page);
  const forgot = page.getByRole('link', { name: 'Parolamı unuttum', exact: true });
  await tabTo(page, forgot, browserName);
  await expect(page.locator('html')).toHaveAttribute('data-at-focus', 'keyboard');
  await expect(forgot).toHaveCSS('outline-width', '0px');
  await expect(forgot).toHaveCSS('box-shadow', 'none');
  await expect(forgot).toHaveCSS('text-decoration-line', 'underline');
  await expect.poll(() => forgot.evaluate((element) => Number.parseFloat(getComputedStyle(element).textDecorationThickness))).toBeGreaterThanOrEqual(2);
  await testInfo.attach('sign-in-keyboard', { body: await page.screenshot(), contentType: 'image/png' });
  await page.keyboard.press('Enter');
  await expect(page.locator('#kc-reset-password-form')).toBeVisible();
  await expect(page.locator('#kc-page-title')).toHaveText('Parolanızı sıfırlayın');
  await expect(page.getByRole('button', { name: 'Gönderin', exact: true })).toBeVisible();
  await expectReadablePage(page);
  const back = page.getByRole('link', { name: 'Oturum açma ekranına dönün', exact: true });
  await tabTo(page, back, browserName);
  await expect(back).toHaveCSS('outline-width', '0px');
  await expect(back).toHaveCSS('box-shadow', 'none');
  await expect(back).toHaveCSS('text-decoration-line', 'underline');
  await testInfo.attach('password-reset-keyboard', { body: await page.screenshot(), contentType: 'image/png' });
  await page.keyboard.press('Enter');
  await expect(page.locator('#kc-form-login')).toBeVisible();
});

const personalInputs = [
  { kind: 'email', value: `privacy-${randomUUID()}@example.test` },
  { kind: 'phone', value: '05550000000' },
  // Deliberately invalid identity number, never a real person's data.
  { kind: 'identity-number', value: '10000000000' },
];

for (const input of personalInputs) {
  for (const flow of ['sign-in', 'password-reset'] as const) {
    test(`G-132: ${flow} keeps the ${input.kind} out of navigation and form addresses`, async ({ page }) => {
      const navigations: string[] = [];
      page.on('request', (request) => {
        if (request.isNavigationRequest()) navigations.push(request.url());
      });
      if (flow === 'sign-in') {
        await openLogin(page);
        await submitPassword(page, input.value);
        await expect(page.locator('#input-error-username')).toBeVisible();
        await expect(page.locator('#username')).toHaveValue(input.value);
      } else {
        await screen('password-reset').open(page);
        await page.locator('#username').fill(input.value);
        await page.getByRole('button', { name: 'Gönderin', exact: true }).click();
        await expect(page.locator('.pf-v5-c-alert')).toContainText('Bu adres kayıtlıysa size bir e-posta gönderdik.');
      }
      expect(navigations.length, 'both opening and submitting the form must navigate').toBeGreaterThanOrEqual(2);
      await expectPrivateAddresses(page, navigations, [input.value]);
    });
  }
}

const maliciousInputs = [
  { kind: 'script', value: '\"><script>window.__identityXss=1</script><input value="' },
  { kind: 'svg-handler', value: '\"><svg onload="window.__identityXss=2"></svg><input value="' },
  { kind: 'image-handler', value: '\"><img src=x onerror="window.__identityXss=3"><input value="' },
];

for (const input of maliciousInputs) {
  test(`G-145: ${input.kind} is escaped in the failed sign-in response`, async ({ page }) => {
    await openLogin(page);
    const responsePromise = page.waitForResponse((response) =>
      response.request().isNavigationRequest() && response.request().method() === 'POST',
    );
    await submitPassword(page, input.value);
    const response = await responsePromise;
    await expect(page.locator('#input-error-username')).toBeVisible();
    await expect(page.locator('#username')).toHaveValue(input.value);
    const html = await response.text();
    expect(html).not.toContain(input.value);
    expect(html).toContain('&lt;');
    expect(html).toContain('window.__identityXss');
    expect(await page.locator('script, svg[onload], img[onerror]').evaluateAll((elements) =>
      elements.some((element) => element.outerHTML.includes('__identityXss')),
    ), 'the payload must not become an executable DOM node').toBe(false);
    expect(await page.evaluate(() => Reflect.get(window, '__identityXss'))).toBeUndefined();
  });
}
