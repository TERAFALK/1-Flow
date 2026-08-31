// Sökbar väljare. Ersätter en <select> när listan kan bli lång – kundregistret
// har hundratals poster och en vanlig rullgardin blir då oanvändbar.
//
// Den befintliga <select>-taggen ligger kvar dold och är fortfarande den som
// formuläret läser av. Det gör att anropande kod kan fortsätta använda
// FormData och form.customer_id.value precis som förut.

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * Gör en befintlig <select> sökbar.
 * @param {HTMLSelectElement|string} target  elementet eller dess id
 * @param {object} opts  { placeholder, minOptions }
 */
export function makeSearchable(target, opts = {}) {
  const select = typeof target === 'string' ? document.getElementById(target) : target;
  if (!select || select.dataset.searchable === '1') return;

  const { placeholder = 'Sök…', minOptions = 8 } = opts;
  // Korta listor är enklare som vanlig rullgardin – ingen anledning att byta ut dem
  if (select.options.length < minOptions) return;

  select.dataset.searchable = '1';
  select.classList.add('hidden');

  const wrap = document.createElement('div');
  wrap.className = 'combo';
  wrap.innerHTML = `
    <input type="text" class="combo-input" placeholder="${esc(placeholder)}" autocomplete="off"
           role="combobox" aria-expanded="false">
    <div class="combo-list hidden"></div>`;
  select.parentNode.insertBefore(wrap, select.nextSibling);

  const input = wrap.querySelector('.combo-input');
  const list = wrap.querySelector('.combo-list');
  let active = -1;

  const options = () => [...select.options].map(o => ({ value: o.value, label: o.textContent.trim() }));

  function labelFor(value) {
    return options().find(o => o.value === value)?.label || '';
  }

  function syncFromSelect() {
    input.value = labelFor(select.value);
  }

  function draw(filter = '') {
    const needle = filter.trim().toLowerCase();
    const matches = options().filter(o => !needle || o.label.toLowerCase().includes(needle));
    active = matches.findIndex(o => o.value === select.value);
    list.innerHTML = matches.length
      ? matches.map((o, i) => `
          <div class="combo-item ${i === active ? 'active' : ''}" data-value="${esc(o.value)}">
            ${esc(o.label) || '<span class="text-muted">–</span>'}
          </div>`).join('')
      : '<div class="combo-empty">Ingen träff</div>';
  }

  function open() {
    draw('');
    list.classList.remove('hidden');
    input.setAttribute('aria-expanded', 'true');
    input.select();
  }

  function close() {
    list.classList.add('hidden');
    input.setAttribute('aria-expanded', 'false');
    // Fritext som inte matchar ska inte bli kvar och se ut som ett val
    syncFromSelect();
  }

  function choose(value) {
    select.value = value;
    // Anropande kod lyssnar på select:ens change (kontaktpersoner, valuta …)
    select.dispatchEvent(new Event('change', { bubbles: true }));
    close();
  }

  input.addEventListener('focus', open);
  input.addEventListener('input', () => {
    list.classList.remove('hidden');
    draw(input.value);
  });

  input.addEventListener('keydown', (e) => {
    const items = [...list.querySelectorAll('.combo-item')];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (list.classList.contains('hidden')) return open();
      active = Math.max(0, Math.min(items.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1)));
      items.forEach((el, i) => el.classList.toggle('active', i === active));
      items[active]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      // Enter i en öppen lista väljer – den ska inte skicka formuläret
      if (!list.classList.contains('hidden') && items[active]) {
        e.preventDefault();
        choose(items[active].dataset.value);
      }
    } else if (e.key === 'Escape') {
      close();
      input.blur();
    }
  });

  list.addEventListener('mousedown', (e) => {
    // mousedown, inte click: blur hinner annars stänga listan först
    const item = e.target.closest('.combo-item');
    if (item) { e.preventDefault(); choose(item.dataset.value); }
  });

  input.addEventListener('blur', () => setTimeout(close, 120));

  // Byter koden select.value programmatiskt (t.ex. snabbskapad kund) ska texten följa med
  select.addEventListener('change', syncFromSelect);
  syncFromSelect();
}

/** Gör alla <select> inom `root` sökbara när de har många alternativ. */
export function makeAllSearchable(root, opts = {}) {
  if (!root) return;
  root.querySelectorAll('select').forEach(sel => makeSearchable(sel, opts));
}
