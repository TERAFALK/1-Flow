/** Dra och släpp filer – gemensam för alla ställen i Flow där något laddas upp.
 *
 *  Ett mail som dras direkt ur Outlook finns inte på disken. Windows lämnar då
 *  ifrån sig en "virtuell" fil, och för den är dataTransfer.files tom –
 *  webbläsaren måste fråga efter innehållet med getAsFileSystemHandle(). Därför
 *  går all filhämtning genom filesFromDataTransfer() istället för att läsa
 *  .files rakt av; annars ser ett släppt mail ut som ett tomt släpp.
 */
import { showToast } from './toast.js';

/** Sant om det som dras är filer och inte t.ex. ett kanban-kort. */
export function hasFiles(dt) {
  return !!dt && [...(dt.types || [])].includes('Files');
}

/**
 * Plockar ut filerna ur ett släpp.
 *
 * MÅSTE anropas synkront i drop-hanteraren: dataTransfer.items töms så fort
 * händelsen är färdigbehandlad, så handtagen hämtas först och väntas in sedan.
 *
 * @returns {Promise<File[]>}
 */
export function filesFromDataTransfer(dt) {
  const items = [...(dt?.items || [])].filter(i => i.kind === 'file');
  if (!items.length) return Promise.resolve([...(dt?.files || [])]);

  const pending = items.map(item => {
    const direct = item.getAsFile?.() || null;
    // En riktig fil har innehåll och behöver inget mer. En virtuell (Outlook)
    // ger antingen null eller en tom platshållare – då krävs handtaget.
    if (direct && direct.size > 0) return Promise.resolve(direct);
    if (!item.getAsFileSystemHandle) return Promise.resolve(direct);
    return item.getAsFileSystemHandle()
      .then(handle => (handle?.kind === 'file' ? handle.getFile() : direct))
      .catch(() => direct);
  });

  return Promise.all(pending).then(files => files.filter(Boolean));
}

// Bara en yta i taget får vara markerad. Ytor ligger inuti varandra – en AOC i
// sitt kort, en anteckning i loggen – och den innersta är den som gäller.
let active = null;
function highlightZone(mark) {
  if (active === mark) return;
  active?.classList.remove('drag-over');
  active = mark;
  mark?.classList.add('drag-over');
}

/** Utan den här landar en fil som missar sin ruta i webbläsarens egen visare –
 *  sidan byts ut och allt osparat är borta. Installeras en gång. */
let guardInstalled = false;
function installGlobalDropGuard() {
  if (guardInstalled) return;
  guardInstalled = true;
  window.addEventListener('dragover', (e) => {
    if (!hasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'none';
    highlightZone(null);        // nås bara utanför ytorna – de stoppar bubblan
  });
  window.addEventListener('drop', (e) => {
    if (hasFiles(e.dataTransfer)) e.preventDefault();
    highlightZone(null);
  });
  // Lämnar pekaren fönstret finns ingen händelse kvar att städa på
  window.addEventListener('dragleave', (e) => { if (!e.relatedTarget) highlightZone(null); });
}

/**
 * Gör ett element till släppyta.
 *
 * @param {Element}  el         ytan som tar emot släppet
 * @param {Function} onFiles    async (File[]) => void
 * @param {object}   opts       highlight: element som markeras (default el)
 * @returns {Function} avbindning
 */
export function dropZone(el, onFiles, { highlight = null } = {}) {
  if (!el) return () => {};
  installGlobalDropGuard();

  const mark = highlight || el;
  el.classList.add('drop-target');

  // dragover avfyras oavbrutet under det som dras, så markeringen sätts där i
  // stället för på dragenter/dragleave – de senare kommer också när pekaren
  // passerar knappar inuti ytan, och markeringen hade blinkat.
  const onOver = (e) => {
    if (!hasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();          // närmaste ytan vinner över kortet omkring
    e.dataTransfer.dropEffect = 'copy';
    highlightZone(mark);
  };
  const onDrop = async (e) => {
    if (!hasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();
    highlightZone(null);
    const files = await filesFromDataTransfer(e.dataTransfer);
    if (!files.length) {
      showToast('Kunde inte läsa det som släpptes. Dra mailet till skrivbordet först och släpp filen därifrån.', 'error', 6000);
      return;
    }
    await onFiles(files);
  };

  el.addEventListener('dragover', onOver);
  el.addEventListener('drop', onDrop);

  return () => {
    el.removeEventListener('dragover', onOver);
    el.removeEventListener('drop', onDrop);
    el.classList.remove('drop-target');
    if (active === mark) highlightZone(null);
  };
}

/** Binder alla element med det givna data-attributet som släppytor.
 *  Hanteraren får attributets värde, så anroparen slipper leta upp id:t. */
export function bindDropZones(root, attr, onFiles) {
  root.querySelectorAll(`[${attr}]`).forEach(el => {
    dropZone(el, (files) => onFiles(el.getAttribute(attr), files, el));
  });
}

/** Lägger släppta filer i en vanlig filruta, så att formuläret sparar dem
 *  precis som om de valts med musen. */
export function setInputFiles(input, files) {
  const dt = new DataTransfer();
  [...(input.files || []), ...files].forEach(f => dt.items.add(f));
  input.files = dt.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
}
