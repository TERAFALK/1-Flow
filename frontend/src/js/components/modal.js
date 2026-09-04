const overlay = () => document.getElementById('modal-overlay');
const box = () => document.getElementById('modal-box');

// Sätts så fort användaren rör ett fält i modalen och nollas när den stängs.
// Programmatisk ifyllnad (kontaktpersoner som laddas in, förvald ansvarig,
// combobox-texten som synkas vid start) sätter värden utan att skicka event,
// så allt som når markDirty kommer från användaren.
let dirty = false;

function markDirty() { dirty = true; }

function onEscape(e) { if (e.key === 'Escape') requestClose(); }
function onOverlayClick(e) { if (e.target === overlay()) requestClose(); }

export function openModal({ title, body, size = '', onClose } = {}) {
  const b = box();
  b.className = `modal-box ${size}`;
  b.innerHTML = `
    <div class="modal-header">
      <h2>${title || ''}</h2>
      <button class="modal-close" id="modal-close-btn">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
      </button>
    </div>
    <div class="modal-body">${typeof body === 'string' ? body : ''}</div>
  `;
  if (typeof body !== 'string' && body instanceof HTMLElement) {
    b.querySelector('.modal-body').appendChild(body);
  }
  overlay().classList.remove('hidden');
  dirty = false;

  document.getElementById('modal-close-btn').addEventListener('click', () => requestClose());
  // Named handlers: addEventListener dedupes same function reference, so
  // repeated openModal calls never stack listeners, and closeModal can remove them.
  overlay().addEventListener('click', onOverlayClick);
  document.addEventListener('keydown', onEscape);
  // Ligger på lådan och inte på formuläret – innehållet byts ut vid varje
  // öppning, men lådan är samma element hela tiden.
  b.addEventListener('input', markDirty);
  b.addEventListener('change', markDirty);

  overlay()._onClose = onClose || null;
}

/** Stänger utan att fråga. Används av koden som redan sparat. */
export function closeModal() {
  const o = overlay();
  if (o.classList.contains('hidden')) return;
  const cb = o._onClose;
  o._onClose = null;
  dirty = false;
  o.classList.add('hidden');
  box().innerHTML = '';
  o.removeEventListener('click', onOverlayClick);
  document.removeEventListener('keydown', onEscape);
  if (cb) cb();
}

/**
 * Stängning på användarens initiativ: klick utanför, Escape, krysset eller
 * Avbryt. Har något ändrats frågar vi först – ett tappat klick utanför ska
 * inte kasta ett halvifyllt formulär.
 *
 * Det är den här som ligger på window.closeModal, alltså den som alla
 * `onclick="closeModal()"` i formulärens sidfot når.
 */
export function requestClose() {
  if (!dirty) return closeModal();
  showUnsavedGuard();
}

function showUnsavedGuard() {
  const b = box();
  if (b.querySelector('.modal-guard')) return;   // redan frågat

  const form = b.querySelector('form');
  const layer = document.createElement('div');
  layer.className = 'modal-guard';
  layer.innerHTML = `
    <div class="modal-guard-panel">
      <p class="modal-guard-title">Spara ändringarna?</p>
      <p class="modal-guard-text">Du har ändringar som inte är sparade.</p>
      <div class="modal-guard-actions">
        <button type="button" class="btn btn-secondary" data-guard="cancel">Fortsätt redigera</button>
        <button type="button" class="btn btn-secondary" data-guard="discard">Kasta ändringar</button>
        ${form ? '<button type="button" class="btn btn-primary" data-guard="save">Spara</button>' : ''}
      </div>
    </div>`;
  b.appendChild(layer);

  layer.addEventListener('click', (e) => {
    const action = e.target.closest('[data-guard]')?.dataset.guard;
    if (!action) return;
    if (action === 'cancel') { layer.remove(); return; }
    if (action === 'discard') { closeModal(); return; }
    // Spara: formulärets egen submit-hanterare sparar och stänger modalen.
    // Går sparningen fel ligger formuläret kvar ifyllt och är fortfarande
    // ändrat, så nästa försök att stänga frågar igen.
    layer.remove();
    form.requestSubmit();
  });

  layer.querySelector('[data-guard="cancel"]').focus();
}

export function modalBody() {
  return box().querySelector('.modal-body');
}

export function confirmDialog(message, confirmLabel = 'Ta bort') {
  return new Promise((resolve) => {
    openModal({
      title: 'Bekräfta',
      body: `
        <p style="margin-bottom:20px">${message}</p>
        <div class="modal-footer" style="padding:0;border:none">
          <button class="btn btn-secondary" id="confirm-no">Avbryt</button>
          <button class="btn btn-danger" id="confirm-yes">${confirmLabel}</button>
        </div>
      `,
      onClose: () => resolve(false),
    });
    // resolve(true) måste ske FÖRE closeModal – closeModal kör onClose som
    // annars hinner resolva false först (ett promise kan bara avgöras en gång).
    document.getElementById('confirm-yes').addEventListener('click', () => { resolve(true); closeModal(); });
    document.getElementById('confirm-no').addEventListener('click', () => closeModal());
  });
}
