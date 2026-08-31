// Enkel stapelgraf i inline-SVG. Projektet har inget diagrambibliotek, och CSP:n
// blockerar CDN – så den ritas för hand, på samma sätt som Gantt-schemat.
//
// Ritas med viewBox och procentbaserad bredd, så den skalar med kortet den ligger
// i utan att behöva mätas om vid fönsterändring.

const VIEW_W = 720;
const VIEW_H = 200;
const PAD_L = 8;      // vänstermarginal i viewBox-enheter
const PAD_B = 26;     // plats för månadsetiketterna
const PAD_T = 14;     // luft ovanför högsta stapeln

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Kortar 1 250 000 till "1,3 M" så att etiketterna får plats. */
function short(n) {
  const abs = Math.abs(n);
  if (abs >= 1e6) return `${(n / 1e6).toLocaleString('sv-SE', { maximumFractionDigits: 1 })} M`;
  if (abs >= 1e3) return `${Math.round(n / 1e3).toLocaleString('sv-SE')} k`;
  return n.toLocaleString('sv-SE', { maximumFractionDigits: 0 });
}

function monthLabel(key) {
  // key är YYYY-MM; Date med dag 1 undviker månadsöverskridningar
  const [y, m] = key.split('-').map(Number);
  const d = new Date(y, m - 1, 1);
  return d.toLocaleDateString('sv-SE', { month: 'short' }).replace('.', '');
}

/**
 * @param {HTMLElement} container
 * @param {object} opts
 *   points    – [{ month: 'YYYY-MM', <valueKey>: number|string }]
 *   valueKey  – vilket fält som ritas
 *   currency  – etikett vid värdena ('EUR' / 'SEK')
 *   color     – stapelfärg
 *   emptyText – vad som visas när allt är noll
 */
export function renderBarChart(container, opts = {}) {
  if (!container) return;
  const {
    points = [], valueKey = 'value', currency = '', emptyText = 'Ingen försäljning i perioden',
    color = 'var(--accent)',
  } = opts;

  const values = points.map(p => Number(p[valueKey]) || 0);
  const max = Math.max(...values, 0);

  if (!points.length || max <= 0) {
    container.innerHTML = `<p class="chart-empty">${esc(emptyText)}</p>`;
    return;
  }

  // Skalan avrundas uppåt till ett jämnt tal så att rutnätet får läsbara värden
  const step = Math.pow(10, Math.floor(Math.log10(max)));
  const top = Math.ceil(max / step) * step || 1;

  const plotH = VIEW_H - PAD_B - PAD_T;
  const slot = (VIEW_W - PAD_L * 2) / points.length;
  const barW = Math.min(slot * 0.6, 46);

  const gridLines = [0, 0.5, 1].map(f => {
    const y = PAD_T + plotH * (1 - f);
    return `
      <line class="chart-grid" x1="${PAD_L}" y1="${y}" x2="${VIEW_W - PAD_L}" y2="${y}"></line>
      <text class="chart-axis" x="${PAD_L}" y="${y - 3}">${short(top * f)}</text>`;
  }).join('');

  const bars = points.map((p, i) => {
    const v = Number(p[valueKey]) || 0;
    const h = Math.max(v > 0 ? 2 : 0, (v / top) * plotH);
    const x = PAD_L + slot * i + (slot - barW) / 2;
    const y = PAD_T + plotH - h;
    const label = `${monthLabel(p.month)} ${p.month.slice(2, 4)}`;
    return `
      <g class="chart-col">
        <rect class="chart-hit" x="${PAD_L + slot * i}" y="${PAD_T}" width="${slot}" height="${plotH}"></rect>
        <rect class="chart-bar" x="${x}" y="${y}" width="${barW}" height="${h}" rx="3"
              style="fill:${color}"></rect>
        <title>${esc(label)}: ${v.toLocaleString('sv-SE', { maximumFractionDigits: 0 })} ${esc(currency)}</title>
        <text class="chart-month" x="${PAD_L + slot * i + slot / 2}" y="${VIEW_H - 8}">${esc(label)}</text>
      </g>`;
  }).join('');

  const total = values.reduce((a, b) => a + b, 0);
  container.innerHTML = `
    <svg class="chart" viewBox="0 0 ${VIEW_W} ${VIEW_H}" preserveAspectRatio="none" role="img"
         aria-label="Sålt värde per månad i ${esc(currency)}">
      ${gridLines}
      ${bars}
    </svg>
    <div class="chart-foot">
      <span>Totalt 12 mån</span>
      <strong>${total.toLocaleString('sv-SE', { maximumFractionDigits: 0 })} ${esc(currency)}</strong>
    </div>`;
}
