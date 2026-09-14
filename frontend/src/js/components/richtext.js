// Formaterad brödtext för de fält som blir underlag i en PDF.
//
// En contenteditable med en liten verktygsrad. Värdet speglas till ett dolt
// <input> med fältets namn, så anropande kod kan fortsätta läsa formuläret med
// FormData precis som när fältet var en vanlig <textarea>.
//
// Innehållet sparas som en liten delmängd HTML (b/i/u, punktlistor, rader) och
// ritas i PDF:en av backend/app/richtext.py. Inklistrad text tas därför in som
// ren text – annars hade Words egna span-taggar följt med in i dokumentet.

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Måste stämma med _HAS_MARKUP i backend/app/richtext.py. span finns med för
// att Chrome lindar infogade tabbar i <span style="white-space:pre">.
const HAS_MARKUP = /<\/?(?:b|strong|i|em|u|br|div|p|ul|ol|li|span)\b[^>]*>/i;

const BUTTONS = [
  { cmd: 'bold', label: 'F', title: 'Fet (Ctrl+B)', style: 'font-weight:700' },
  { cmd: 'italic', label: 'K', title: 'Kursiv (Ctrl+I)', style: 'font-style:italic' },
  { cmd: 'underline', label: 'U', title: 'Understruken (Ctrl+U)', style: 'text-decoration:underline' },
  { cmd: 'insertUnorderedList', label: '•—', title: 'Punktlista' },
  { cmd: 'removeFormat', label: '⌫', title: 'Rensa formatering' },
  { cmd: 'alignColumns', label: '⇥≡', title: 'Rada upp kolumner' },
];

// ── Kolumner ──────────────────────────────────────────────────────────────────
// Rader av typen "etikett<tabb>värde" ska ha värdet i samma kolumn. Tabbarna
// hamnar på tabbstopp, så hur många som behövs beror på hur bred etiketten är
// – och den bredden ändras så fort etiketten skrivs om eller översätts. Samma
// antal tabbar efter "antal fack" som efter "number of compartments" landar på
// ett helt annat ställe.
//
// Bredden måste mätas i pixlar: redigeraren har ett proportionellt typsnitt,
// där ett "m" är flera gånger bredare än ett mellanslag. Därför görs det här
// och inte i backend.

// Samma gränser som backend/app/richtext.py använder för att känna igen en
// spaltrad i PDF:en. En uppradad rad måste fortfarande kännas igen där.
const MAX_LABEL_CHARS = 40;
const MIN_BODY_COLUMN = 24;
const PDF_TAB_COLUMNS = 8;

const LINE_SEPARATOR = /(\n|<br\s*\/?>|<\/div>\s*<div[^>]*>|<\/?div[^>]*>)/i;
const TAB_RUN = /(?:<span\b[^>]*>\t+<\/span>|\t)+/;

function visibleText(markup) {
  const el = document.createElement('div');
  el.innerHTML = markup;
  return el.textContent;
}

/** En rad "etikett<tabb>värde" som börjar i vänsterkanten, annars null. */
function parseLabelRow(line) {
  // Indragna rader hör till stycket ovanför – samma regel som i PDF:en
  if (/^(?:<[^>]+>)*[ \t]/.test(line)) return null;
  const match = TAB_RUN.exec(line);
  if (!match) return null;
  const label = line.slice(0, match.index);
  const value = line.slice(match.index + match[0].length);
  // Fler tabbföljder på raden betyder en tabell ("Artikel<tabb>Antal<tabb>Pris").
  // Att dra ut dess första kolumn skulle få PDF:en att läsa den som en spaltrad
  // och slå ihop resten av kolumnerna – den lämnas som den är.
  if (TAB_RUN.test(value)) return null;
  const labelText = visibleText(label);
  if (!labelText.trim() || !visibleText(value).trim()) return null;
  if (labelText.trim().length > MAX_LABEL_CHARS) return null;
  return {
    label, value, labelText,
    bold: /<(?:b|strong)\b/i.test(label),
    // Chrome lindar tabbarna i en span – behåll samma form på den nya raden
    spanOpen: match[0].startsWith('<span') ? match[0].match(/^<span\b[^>]*>/)[0] : null,
  };
}

/** Kolumnen efter n tabbar från position c, räknat i tecken som PDF:en gör. */
function pdfColumn(chars, tabs) {
  let column = chars;
  for (let i = 0; i < tabs; i++) column = (Math.floor(column / PDF_TAB_COLUMNS) + 1) * PDF_TAB_COLUMNS;
  return column;
}

/**
 * Radar upp värdena i alla block av spaltrader. Ändrar bara antalet tabbar
 * mellan etikett och värde – aldrig texten. Returnerar true om något ändrades.
 */
export async function alignColumns(editor) {
  // Typsnittet måste vara laddat, annars mäts reservtypsnittet
  if (document.fonts?.ready) { try { await document.fonts.ready; } catch { /* mät ändå */ } }

  const cs = getComputedStyle(editor);
  const fontFor = (weight) => `${cs.fontStyle} ${weight} ${cs.fontSize} ${cs.fontFamily}`;
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.font = fontFor(cs.fontWeight);
  const space = ctx.measureText(' ').width || 4;
  const stop = (parseFloat(cs.tabSize) || 8) * space;
  // En tabb som skulle landa närmare än ett halvt tecken hoppar till nästa stopp
  // (så beter sig CSS) – räkna med samma regel
  const nextStop = (pos) => {
    let s = (Math.floor(pos / stop) + 1) * stop;
    if (s - pos < space * 0.5) s += stop;
    return s;
  };
  const widthOf = (row) => {
    ctx.font = fontFor(row.bold ? 700 : cs.fontWeight);
    return ctx.measureText(row.labelText).width;
  };
  const tabsTo = (width, target) => {
    let pos = width, count = 0;
    while (pos < target - 0.01 && count < 60) { pos = nextStop(pos); count++; }
    return Math.max(count, 1);
  };

  const original = editor.innerHTML;
  const parts = original.split(LINE_SEPARATOR);

  // Block = rader i följd som alla är spaltrader. Allt annat bryter blocket,
  // även en tom rad – två listor med en blankrad emellan radas upp var för sig.
  const blocks = [];
  let current = null;
  parts.forEach((part, index) => {
    if (index % 2 === 1) return;                 // radavskiljare
    const row = parseLabelRow(part);
    if (!row) { current = null; return; }
    row.index = index;
    if (!current) { current = []; blocks.push(current); }
    current.push(row);
  });

  for (const block of blocks) {
    block.forEach(row => { row.width = widthOf(row); });
    // Första stoppet som ligger förbi den bredaste etiketten
    let target = nextStop(Math.max(...block.map(r => r.width)));
    // Varje rad måste också kännas igen som spaltrad i PDF:en, vilket kräver
    // att värdet börjar tillräckligt långt in även räknat i tecken
    for (let guard = 0; guard < 20; guard++) {
      block.forEach(row => { row.tabs = tabsTo(row.width, target); });
      if (block.every(r => pdfColumn(r.labelText.length, r.tabs) >= MIN_BODY_COLUMN)) break;
      target += stop;
    }
    block.forEach(row => {
      const run = row.spanOpen
        ? `${row.spanOpen}${'\t'.repeat(row.tabs)}</span>`
        : '\t'.repeat(row.tabs);
      parts[row.index] = row.label + run + row.value;
    });
  }

  const aligned = parts.join('');
  if (aligned === original) return false;
  editor.innerHTML = aligned;
  return true;
}

/**
 * HTML för ett formaterat fält. Ger samma formulärvärde som en <textarea>.
 * @param {string} name   fältnamnet i formuläret
 * @param {string} value  sparat värde (HTML, eller ren text från äldre poster)
 * @param {object} opts   { rows }
 */
export function richTextField(name, value, opts = {}) {
  const { rows = 6 } = opts;
  // Ett gammalt värde utan våra taggar är ren text och måste escapas innan det
  // läggs in i en contenteditable. Testet gäller taggarna redigeraren själv
  // skapar – ett ensamt "<" i löpande text ("5 < 6") är inte markup.
  const initial = HAS_MARKUP.test(value || '')
    ? value
    : esc(value).replace(/\n/g, '<br>');

  return `
    <div class="richtext" data-rich-for="${esc(name)}">
      <div class="richtext-toolbar">
        ${BUTTONS.map(b => `
          <button type="button" class="richtext-btn" data-cmd="${b.cmd}"
                  title="${esc(b.title)}" style="${b.style || ''}">${b.label}</button>`).join('')}
        <span class="richtext-hint">Tabb för indrag</span>
      </div>
      <div class="richtext-input" contenteditable="true"
           style="min-height:${rows * 1.5}em">${initial}</div>
      <input type="hidden" name="${esc(name)}">
    </div>`;
}

/** Kör ett formateringskommando som taggar (<b>) och inte som CSS.
 *  Backend känner bara igen taggarna – ett <span style> hade tappats bort. */
function exec(cmd) {
  try { document.execCommand('styleWithCSS', false, false); } catch { /* stöds inte överallt */ }
  document.execCommand(cmd);
}

/** Kopplar alla formaterade fält inom `root`. Anropas efter att formuläret ritats. */
export function bindRichText(root) {
  if (!root) return;
  root.querySelectorAll('.richtext').forEach(wrap => {
    const editor = wrap.querySelector('.richtext-input');
    const hidden = wrap.querySelector('input[type="hidden"]');

    const sync = () => {
      // Tomt fält ska sparas som tomt, inte som webbläsarens <br> eller <div><br></div>
      const text = editor.textContent.replace(/ /g, ' ').trim();
      hidden.value = text ? editor.innerHTML : '';
    };
    sync();

    editor.addEventListener('input', sync);

    // Inklistrat tas in som ren text – Words markup ska inte in i dokumentet
    editor.addEventListener('paste', (e) => {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, text);
    });

    editor.addEventListener('keydown', (e) => {
      // Tabb gör indrag i stället för att hoppa vidare i formuläret. Shift+Tab
      // lämnar fältet, så det går fortfarande att ta sig ut med tangentbordet.
      if (e.key === 'Tab' && !e.shiftKey) {
        e.preventDefault();
        document.execCommand('insertText', false, '\t');
        sync();
        return;
      }
      // Enter hanteras själv i stället för att lämnas åt webbläsaren. Med
      // white-space: pre-wrap gör Chrome olika saker beroende på var markören
      // står – ibland <div>, ibland ett rent radbrytningstecken, ibland inget
      // alls. insertLineBreak ger alltid ett <br>, som utskriften förstår.
      if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        document.execCommand('insertLineBreak');
        sync();
        return;
      }
      const ctrl = e.ctrlKey || e.metaKey;
      if (!ctrl) return;
      const cmd = { b: 'bold', i: 'italic', u: 'underline' }[e.key.toLowerCase()];
      if (cmd) { e.preventDefault(); exec(cmd); sync(); }
    });

    wrap.querySelectorAll('.richtext-btn').forEach(btn => {
      // mousedown, inte click: annars hinner markeringen i fältet försvinna
      btn.addEventListener('mousedown', async (e) => {
        e.preventDefault();
        if (btn.dataset.cmd === 'alignColumns') {
          // Räknas som en ändring av användaren – input-händelsen gör att
          // formuläret vet att det finns något osparat
          if (await alignColumns(editor)) editor.dispatchEvent(new Event('input', { bubbles: true }));
          return;
        }
        editor.focus();
        exec(btn.dataset.cmd);
        sync();
      });
    });
  });
}
