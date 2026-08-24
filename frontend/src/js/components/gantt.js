import { downloadFile, printFile } from '../api.js';
import { showToast } from './toast.js';

// Gantt-schema, delat av arbetsorder (faser) och Försäljning (aktiviteter).
//
// Pixlar per dag för respektive zoomnivå. Timeline-bredden räknas i px istället
// för procent – då trycks inte schemat ihop när posterna blir fler, utan växer
// och scrollar i sidled.
const GANTT_SCALES = {
  dag:    { px: 32, label: 'Dag' },
  vecka:  { px: 13, label: 'Vecka' },
  manad:  { px: 4.5, label: 'Månad' },
};
const GANTT_LABEL_W = 180;
const DAY_MS = 86400000;

const PRINT_ICON = `<svg viewBox="0 0 20 20" fill="currentColor" width="15"><path fill-rule="evenodd" d="M5 4v3H4a2 2 0 00-2 2v3a2 2 0 002 2h1v2a1 1 0 001 1h8a1 1 0 001-1v-2h1a2 2 0 002-2V9a2 2 0 00-2-2h-1V4a1 1 0 00-1-1H6a1 1 0 00-1 1zm2 0h6v3H7V4zm6 8H7v4h6v-4z" clip-rule="evenodd"/></svg>`;
const DOWNLOAD_ICON = `<svg viewBox="0 0 20 20" fill="currentColor" width="15"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM9.293 13.707a1 1 0 001.414 0l4-4a1 1 0 00-1.414-1.414L11 10.586V3a1 1 0 10-2 0v7.586L6.707 8.293a1 1 0 00-1.414 1.414l4 4z" clip-rule="evenodd"/></svg>`;

// Vald zoom lever kvar mellan omritningar (t.ex. när en post sparas). Så länge
// användaren inte valt själv sätts nivån automatiskt efter periodens längd.
let ganttScale = null;
let ganttScaleChosen = false;

const toDay = (value) => {
  const d = new Date(String(value).slice(0, 10) + 'T00:00:00');
  return isNaN(d) ? null : d;
};
const daysBetween = (a, b) => Math.round((b - a) / DAY_MS);
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const startOfWeek = (d) => addDays(d, -((d.getDay() || 7) - 1));
const fmtDay = (d) => d ? d.toLocaleDateString('sv-SE', { day: 'numeric', month: 'short' }) : '–';

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * Ritar ett Gantt-schema i `container`.
 *
 * @param {HTMLElement} container
 * @param {object} opts
 *   items       – [{name, color, start_date, end_date, source, activity_id}]
 *   labelHeader – rubrik över namnkolumnen ("Fas" / "Aktivitet")
 *   emptyHtml   – vad som visas när listan är tom
 *   pdfUrl      – valfri API-sökväg för utskrift/nedladdning
 *   pdfName     – filnamn vid nedladdning
 *   onRowClick  – valfri callback(item) när en rad klickas
 */
export function renderGantt(container, opts = {}) {
  if (!container) return;
  const {
    items = [], labelHeader = 'Aktivitet', emptyHtml = '', pdfUrl = null,
    pdfName = 'gantt.pdf', onRowClick = null, title = 'Gantt-schema',
  } = opts;

  if (!items.length) {
    container.innerHTML = `
      <div class="card">
        <div class="card-header"><span class="card-title">${esc(title)}</span></div>
        <div class="card-body">
          ${emptyHtml || '<p class="text-muted" style="font-size:13px;margin:0">Inget att visa än.</p>'}
        </div>
      </div>`;
    return;
  }

  const rows = items.map(p => ({ ...p, start: toDay(p.start_date), end: toDay(p.end_date) }));
  const dated = rows.filter(p => p.start || p.end);
  // Poster med bara ett datum behandlas som endagsaktiviteter
  dated.forEach(p => { p.start = p.start || p.end; p.end = p.end || p.start; });
  dated.forEach(p => { if (p.end < p.start) [p.start, p.end] = [p.end, p.start]; });

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const allDates = dated.flatMap(p => [p.start, p.end]);
  const rawMin = allDates.length ? new Date(Math.min(...allDates)) : today;
  const rawMax = allDates.length ? new Date(Math.max(...allDates)) : addDays(today, 14);

  // Hela veckor med lite luft i kanterna, och alltid med dagens datum synligt
  const min = startOfWeek(addDays(new Date(Math.min(rawMin, today)), -3));
  const max = addDays(startOfWeek(addDays(new Date(Math.max(rawMax, today)), 3)), 6);
  const totalDays = Math.max(daysBetween(min, max) + 1, 7);

  // Auto-zoom: korta perioder i dagvy, långa i månadsvy
  if (!ganttScaleChosen) ganttScale = totalDays <= 21 ? 'dag' : totalDays <= 130 ? 'vecka' : 'manad';
  const px = GANTT_SCALES[ganttScale].px;
  const trackW = Math.round(totalDays * px);
  const x = (d) => Math.round(daysBetween(min, d) * px);

  // ── Månadsband ──
  const months = [];
  for (let d = new Date(min.getFullYear(), min.getMonth(), 1); d <= max; d.setMonth(d.getMonth() + 1)) {
    const from = new Date(Math.max(d, min));
    const to = new Date(Math.min(new Date(d.getFullYear(), d.getMonth() + 1, 0), max));
    const w = (daysBetween(from, to) + 1) * px;
    if (w > 1) {
      months.push({
        left: x(from), width: Math.round(w),
        name: d.toLocaleDateString('sv-SE', { month: 'long', year: 'numeric' }),
      });
    }
  }

  // ── Tickar och rutnät ──
  const dayMode = px >= 24;
  const ticks = [];
  const gridLines = [];
  const weekends = [];
  for (let i = 0; i < totalDays; i++) {
    const d = addDays(min, i);
    const isMonday = d.getDay() === 1;
    if (dayMode) {
      ticks.push({ left: x(d), width: Math.round(px), text: String(d.getDate()), strong: isMonday });
      gridLines.push({ left: x(d), strong: isMonday });
      if (d.getDay() === 0 || d.getDay() === 6) weekends.push({ left: x(d), width: Math.round(px) });
    } else if (isMonday) {
      ticks.push({ left: x(d), width: Math.round(px * 7), text: `v.${isoWeekNumber(d)}`, strong: false });
      gridLines.push({ left: x(d), strong: true });
    }
  }
  const todayVisible = today >= min && today <= max;

  // ── Rader ──
  const rowHtml = rows.map((p, i) => {
    const color = p.color || 'var(--accent)';
    // Egna aktiviteter går att klicka på; automatiska poster kommer ur datumfält
    const clickable = onRowClick && p.source === 'custom';
    const attrs = `data-gantt-row="${i}"${clickable ? ' class="gantt2-row clickable"' : ' class="gantt2-row"'}`;
    const nameCell = `
      <div class="gantt2-label">
        <span class="gantt2-dot" style="background:${esc(color)}"></span>
        <span class="gantt2-name" title="${esc(p.name)}">${esc(p.name)}</span>`;
    if (!p.start) {
      return `
        <div ${attrs}>
          ${nameCell}</div>
          <div class="gantt2-track" style="width:${trackW}px">
            <span class="gantt2-undated">Inget datum angivet</span>
          </div>
        </div>`;
    }
    const left = x(p.start);
    const width = Math.max(Math.round((daysBetween(p.start, p.end) + 1) * px), 6);
    const period = `${fmtDay(p.start)} – ${fmtDay(p.end)}`;
    const days = daysBetween(p.start, p.end) + 1;
    const inside = width >= 110;
    return `
      <div ${attrs}>
        ${nameCell}
          <span class="gantt2-days">${days} d</span>
        </div>
        <div class="gantt2-track" style="width:${trackW}px">
          <div class="gantt2-bar" style="left:${left}px;width:${width}px;background:${esc(color)}" title="${esc(p.name)}: ${period}">
            ${inside ? `<span>${period}</span>` : ''}
          </div>
          ${inside ? '' : `<span class="gantt2-bar-tag" style="left:${left + width + 6}px">${period}</span>`}
        </div>
      </div>`;
  }).join('');

  container.innerHTML = `
    <div class="card">
      <div class="card-header">
        <span class="card-title">${esc(title)}</span>
        <div class="gantt2-tools">
          <span class="text-muted" style="font-size:12px">${fmtDay(rawMin)} – ${fmtDay(rawMax)}</span>
          <div class="gantt2-zoom" data-gantt-zoom>
            ${Object.entries(GANTT_SCALES).map(([key, s]) =>
              `<button type="button" data-scale="${key}" class="${key === ganttScale ? 'active' : ''}">${s.label}</button>`
            ).join('')}
          </div>
          ${pdfUrl ? `
            <button class="btn btn-ghost btn-sm" data-gantt-print title="Skriv ut i liggande A4">${PRINT_ICON} Skriv ut</button>
            <button class="btn btn-ghost btn-sm" data-gantt-download title="Ladda ner som PDF">${DOWNLOAD_ICON}</button>` : ''}
        </div>
      </div>
      <div class="card-body" style="padding:0">
        <div class="gantt2-scroll" data-gantt-scroll>
          <div class="gantt2-inner" style="width:${GANTT_LABEL_W + trackW}px;--gantt-label-w:${GANTT_LABEL_W}px">
            <div class="gantt2-head">
              <div class="gantt2-label gantt2-corner">${esc(labelHeader)}</div>
              <div class="gantt2-axis" style="width:${trackW}px">
                <div class="gantt2-months">
                  ${months.map(m => `<div class="gantt2-month" style="left:${m.left}px;width:${m.width}px">${m.name}</div>`).join('')}
                </div>
                <div class="gantt2-ticks">
                  ${ticks.map(t => `<div class="gantt2-tick ${t.strong ? 'strong' : ''}" style="left:${t.left}px;width:${t.width}px">${t.text}</div>`).join('')}
                </div>
              </div>
            </div>
            <div class="gantt2-rows">
              <div class="gantt2-grid" style="left:${GANTT_LABEL_W}px;width:${trackW}px">
                ${weekends.map(w => `<div class="gantt2-weekend" style="left:${w.left}px;width:${w.width}px"></div>`).join('')}
                ${gridLines.map(g => `<div class="gantt2-line ${g.strong ? 'strong' : ''}" style="left:${g.left}px"></div>`).join('')}
                ${todayVisible ? `<div class="gantt2-today" style="left:${x(today)}px" title="Idag ${fmtDay(today)}"></div>` : ''}
              </div>
              ${rowHtml}
            </div>
          </div>
        </div>
      </div>
    </div>
  `;

  container.querySelector('[data-gantt-zoom]').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-scale]');
    if (!btn || btn.dataset.scale === ganttScale) return;
    ganttScale = btn.dataset.scale;
    ganttScaleChosen = true;
    renderGantt(container, opts);
  });

  if (onRowClick) {
    container.querySelectorAll('[data-gantt-row]').forEach(row => {
      const item = rows[Number(row.dataset.ganttRow)];
      if (item?.source !== 'custom') return;
      row.addEventListener('click', () => onRowClick(item));
    });
  }

  if (pdfUrl) {
    // Utskriften är alltid liggande A4 och skalas för att rymma hela perioden –
    // zoomnivån på skärmen påverkar den inte
    container.querySelector('[data-gantt-print]').addEventListener('click', async () => {
      try { await printFile(pdfUrl); } catch (err) { showToast(err.message, 'error'); }
    });
    container.querySelector('[data-gantt-download]').addEventListener('click', async () => {
      try { await downloadFile(pdfUrl, pdfName); } catch (err) { showToast(err.message, 'error'); }
    });
  }

  // Scrolla fram dagens datum (eller periodens start) istället för att börja i kanten
  const scroller = container.querySelector('[data-gantt-scroll]');
  const focusX = x(todayVisible ? today : rawMin);
  scroller.scrollLeft = Math.max(0, focusX - scroller.clientWidth / 3);
}

export function isoWeekNumber(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}
