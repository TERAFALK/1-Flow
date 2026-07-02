const BASE = '/api';

async function request(url, options = {}) {
  const token = localStorage.getItem('flow_token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(`${BASE}${url}`, { ...options, headers });

  if (res.status === 401) {
    localStorage.removeItem('flow_token');
    localStorage.removeItem('flow_user');
    window.dispatchEvent(new CustomEvent('flow:unauthorized'));
    throw new Error('Session utgången – logga in igen');
  }

  if (res.status === 204) return null;

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
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
