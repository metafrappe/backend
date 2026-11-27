// Central keyboard focus mode for the account console.
// The mode starts off. Only Tab and Shift+Tab turn it on. Pointer and touch input turn it off.
// The focus indicators in atonota-account.css depend on this state and on :focus-visible.
// This script never calls blur() and never blocks a key. It moves focus in one case only: a type-ahead select
// drops focus to the page body when an option is picked with the keyboard, and the script gives it back to the field.
const root = document.documentElement;
root.setAttribute('data-at-js', '');

document.addEventListener(
  'keydown',
  (event) => {
    if (event.key === 'Tab' && !event.ctrlKey && !event.metaKey) {
      root.setAttribute('data-at-focus', 'keyboard');
    }
  },
  true,
);

// A type-ahead select closes its option list after Enter or Space and focus falls to the page body.
// The field gets focus back, so the keyboard user stays in place. The field's "aria-controls" link points to
// an id that the console never renders, so the script remembers the last focused type-ahead field instead.
let lastTypeahead = null;
document.addEventListener(
  'focusin',
  (event) => {
    if (event.target.matches?.('input[role="combobox"]')) lastTypeahead = event.target;
  },
  true,
);

document.addEventListener(
  'keydown',
  (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const option = event.target.closest?.('[role="listbox"] [role="option"]');
    const field = lastTypeahead;
    // Only the list of that field counts: the field says its list is open. Other lists, such as the page size
    // menu, are left alone.
    if (!option || !field?.isConnected || field.getAttribute('aria-expanded') !== 'true') return;
    // The console closes the list on its next render. Focus is checked until that render has happened.
    const giveBack = (tries) => {
      if (!document.activeElement || document.activeElement === document.body) field.focus();
      else if (tries > 0 && document.activeElement === option) requestAnimationFrame(() => giveBack(tries - 1));
    };
    requestAnimationFrame(() => giveBack(10));
  },
  true,
);

const pointerMode = () => root.removeAttribute('data-at-focus');

document.addEventListener('pointerdown', pointerMode, true);
document.addEventListener('touchstart', pointerMode, { capture: true, passive: true });

// Brand name. The stock console shows only a logo image. The page title holds the brand name
// (theme property "title", filled from the IDENTITY_BRAND_NAME variable).
// The name is handed to the stylesheet as a custom property and drawn there as a pseudo-element,
// so the console markup stays untouched and React re-renders cannot remove it.
root.style.setProperty('--at-brand-name', JSON.stringify(document.title));

// Accessibility repairs for the stock console markup.
// The console renders some overflow-menu toggles (three dots) without an accessible name, and the title of an
// inline alert as a fourth-level heading right under a first-level one. A theme cannot change the console
// markup, so the missing attributes are added here. The names come from the theme message bundle
// (keys "atAccountMenu", "atMoreActions", "atPagination" and "atPaginationBottom"), so they are translated like every other text.
const environment = JSON.parse(document.getElementById('environment')?.textContent ?? '{}');
const messagesUrl = `${environment.serverBaseUrl}/resources/${environment.realm}/account/${environment.locale}`;

const repair = (names) => {
  for (const toggle of document.querySelectorAll('button.pf-v5-c-menu-toggle.pf-m-plain:not([aria-label]):not([aria-labelledby])')) {
    if (toggle.textContent.trim() !== '') continue;
    if (toggle.closest('.pf-v5-c-masthead')) {
      toggle.setAttribute('aria-label', names.atAccountMenu);
      continue;
    }
    // A toggle in a section row is named after its section, for example "Passkey: More actions".
    const heading = toggle.closest('.pf-v5-l-split')?.querySelector('.pf-v5-c-title, h1, h2, h3')?.textContent.trim();
    toggle.setAttribute('aria-label', heading ? `${heading}: ${names.atMoreActions}` : names.atMoreActions);
  }
  for (const title of document.querySelectorAll('h4.pf-v5-c-alert__title:not([aria-level])')) {
    title.setAttribute('aria-level', '2');
  }
  // The groups page shows a standalone checkbox in each row and no label. The name is built from the row and
  // the column header, for example "Sample team: Direct membership". Both texts are already on the page.
  for (const box of document.querySelectorAll('.pf-v5-c-check.pf-m-standalone > input:not([aria-label]):not([aria-labelledby])')) {
    if (box.labels?.length) continue;
    const row = box.closest('.pf-v5-c-data-list__item-content');
    const cell = box.closest('.pf-v5-c-data-list__cell');
    if (!row || !cell) continue;
    const index = [...row.children].indexOf(cell);
    const header = row.closest('.pf-v5-c-data-list')?.querySelector('[id$="-columns-names"] .pf-v5-c-data-list__item-content')?.children[index]?.textContent.trim();
    const name = row.children[0]?.textContent.trim();
    if (header && name) box.setAttribute('aria-label', `${name}: ${header}`);
  }
  // Pagination landmarks share one English name. A page with two lists, such as linked accounts, has several.
  // Each one is named after the heading of its own list and its place at the start or the end of the list.
  for (const nav of document.querySelectorAll('nav.pf-v5-c-pagination__nav')) {
    const heading = nav.closest('.pf-v5-l-stack__item, .pf-v5-c-page__main-section')?.querySelector('h1, h2, h3')?.textContent.trim();
    // The list end has a second pagination with the same name. It gets its own name.
    const own = nav.closest('.pf-v5-c-pagination.pf-m-bottom, [id$="-bottom-pagination"]') ? names.atPaginationBottom : names.atPagination;
    const label = heading ? `${heading}: ${own}` : own;
    if (nav.getAttribute('aria-label') !== label) nav.setAttribute('aria-label', label);
  }
};

try {
  const response = await fetch(messagesUrl, { credentials: 'same-origin' });
  if (response.ok) {
    const names = Object.fromEntries((await response.json()).map((entry) => [entry.key, entry.value]));
    if (names.atAccountMenu && names.atMoreActions && names.atPagination && names.atPaginationBottom) {
      repair(names);
      // The console draws its pages after this script runs and redraws them on navigation.
      new MutationObserver(() => repair(names)).observe(document.body, { childList: true, subtree: true });
    }
  }
} catch {
  // Without the names the toggles stay as the stock console draws them. Nothing else depends on this request.
}
