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
];

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
      btn.addEventListener('mousedown', (e) => {
        e.preventDefault();
        editor.focus();
        exec(btn.dataset.cmd);
        sync();
      });
    });
  });
}
