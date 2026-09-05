const BASE = '/api';

async function request(url, options = {}) {
  const token = localStorage.getItem('flow_token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(`${BASE}${url}`, { ...options, headers });

  // 401 från inloggningen betyder "fel uppgifter", inte "utgången session" – den
  // ska visas i formulärets felruta, inte kasta tillbaka till inloggningsskärmen
  // (vilket skulle dölja meddelandet och nollställa teknikerväljaren).
  if (res.status === 401 && !url.startsWith('/auth/')) {
    localStorage.removeItem('flow_token');
    localStorage.removeItem('flow_user');
    window.dispatchEvent(new CustomEvent('flow:unauthorized'));
    throw new Error('Session utgången – logga in igen');
  }

  if (res.status === 204) return null;

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // detail är oftast en sträng, men en endpoint kan svara med ett objekt när
    // felet bär data som anroparen behöver (t.ex. 409 med veckan som redan
    // finns). Meddelandet plockas då ur objektet, och objektet följer med.
    const detail = data.detail;
    const structured = detail && typeof detail === 'object';
    const error = new Error(
      (structured ? detail.message : detail) || `HTTP ${res.status}`
    );
    if (structured) error.detail = detail;
    error.status = res.status;
    throw error;
  }
  return data;
}

export const api = {
  get:    (url)        => request(url),
  post:   (url, body)  => request(url, { method: 'POST',   body: JSON.stringify(body) }),
  put:    (url, body)  => request(url, { method: 'PUT',    body: JSON.stringify(body) }),
  patch:  (url, body)  => request(url, { method: 'PATCH',  body: JSON.stringify(body) }),
  delete: (url)        => request(url, { method: 'DELETE' }),
};

export async function uploadFile(url, formData) {
  const token = localStorage.getItem('flow_token');
  const res = await fetch(`${BASE}${url}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  if (res.status === 413) throw new Error('Filen är för stor för servern (öka client_max_body_size i proxyn)');
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

/** Hämtar en PDF och öppnar den i en ny flik med utskriftsdialogen. */
export async function printFile(url) {
  const token = localStorage.getItem('flow_token');
  const res = await fetch(`${BASE}${url}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const objUrl = URL.createObjectURL(await res.blob());
  const win = window.open(objUrl, '_blank');
  if (!win) {
    URL.revokeObjectURL(objUrl);
    throw new Error('Popup blockerad – tillåt popup-fönster för att skriva ut');
  }
  // PDF-visaren har egen utskriftsknapp om load-eventet inte hinner triggas
  win.addEventListener('load', () => { try { win.print(); } catch {} }, { once: true });
  setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
}

export async function downloadFile(url, filename) {
  const token = localStorage.getItem('flow_token');
  const res = await fetch(`${BASE}${url}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objUrl);
}
