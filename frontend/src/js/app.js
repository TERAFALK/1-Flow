import { api } from './api.js';
import { showToast } from './components/toast.js';
import { renderDashboard } from './pages/dashboard.js';
import { renderWorkOrders, renderNewWorkOrder, renderWorkOrderDetail } from './pages/work-orders.js';
import { renderCustomers, renderCustomerDetail } from './pages/customers.js';
import { renderVehicles, renderVehicleDetail } from './pages/vehicles.js';
import { renderArticles } from './pages/articles.js';
import { renderScanner } from './pages/scanner.js';
import { renderTimeEntries } from './pages/time-entries.js';
import { renderCalendar } from './pages/calendar.js';
import { renderUsers } from './pages/users.js';
import { renderSettings } from './pages/settings.js';
import { renderPickLists } from './pages/pick-lists.js';

console.log('Flow app.js loaded', new Date().toISOString());

window.addEventListener('error', (e) => {
  console.error('Ohanterat fel:', e.error || e.message);
  showToast(`Fel: ${e.error?.message || e.message}`, 'error');
});
window.addEventListener('unhandledrejection', (e) => {
  console.error('Ohanterat promise-fel:', e.reason);
  showToast(`Fel: ${e.reason?.message || e.reason}`, 'error');
});
document.addEventListener('securitypolicyviolation', (e) => {
  console.error('CSP-blockering:', e.violatedDirective, e.blockedURI, e.sourceFile, e.lineNumber);
  showToast(`CSP blockerar: ${e.violatedDirective}`, 'error');
});

// ── Helpers (exported for page modules) ──────────────────────────────────────

export function statusBadge(status) {
  const labels = { ny: 'Ny', planerad: 'Planerad', pagaende: 'Pågående', klar: 'Klar', fakturerad: 'Fakturerad' };
  return `<span class="badge badge-${status}">${labels[status] || status}</span>`;
}

export function fmtDate(iso, withTime = false) {
  if (!iso) return '–';
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  const date = d.toLocaleDateString('sv-SE');
  if (!withTime) return date;
  return `${date} ${d.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' })}`;
}

export function fmtDuration(minutes) {
  if (!minutes && minutes !== 0) return '–';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

// ── Router ────────────────────────────────────────────────────────────────────

function parseHash() {
  const hash = window.location.hash.replace('#', '') || '/dashboard';
  const [path, qs] = hash.split('?');
  const params = {};
  if (qs) qs.split('&').forEach(p => { const [k, v] = p.split('='); params[k] = decodeURIComponent(v || ''); });
  return { path, params };
}

const PAGE_TITLES = {
  '/dashboard':    'Översikt',
  '/work-orders':  'Arbetsorder',
  '/customers':    'Kunder',
  '/vehicles':     'Fordon',
  '/scanner':      'Scanner',
  '/articles':     'Artiklar',
  '/pick-lists':   'Plocklistor',
  '/time-entries': 'Tidrapportering',
  '/calendar':     'Kalender',
  '/users':        'Användare',
  '/settings':     'Inställningar',
};

// Pages a non-admin (tekniker) is allowed to open. Everything else redirects here.
const TEKNIKER_ALLOWED = ['/scanner'];

function currentRole() {
  try { return JSON.parse(localStorage.getItem('flow_user') || '{}').role; }
  catch { return null; }
}

async function route() {
  const { path, params } = parseHash();

  // Role gate: technicians only get the scanner
  if (currentRole() && currentRole() !== 'admin') {
    const base = '/' + path.split('/')[1];
    if (!TEKNIKER_ALLOWED.includes(base)) {
      if (location.hash !== '#/scanner') { location.hash = '#/scanner'; return; }
    }
  }

  const content = document.getElementById('page-content');
  content.innerHTML = '<div class="loading">Laddar…</div>';

  // Clear topbar actions on each route
  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = '';

  // Update topbar title
  const titleEl = document.getElementById('topbar-title');
  if (titleEl) {
    const base = '/' + path.split('/')[1];
    titleEl.textContent = PAGE_TITLES[base] || 'Flow';
  }

  // Update nav active state
  document.querySelectorAll('.nav-item').forEach(item => {
    const page = '/' + (item.dataset.page || '');
    item.classList.toggle('active', path.startsWith(page));
  });

  try {
    const idMatch = path.match(/^(\/[\w-]+)\/(\d+)$/);
    if (idMatch) {
      const [, base, id] = idMatch;
      if (base === '/work-orders') return await renderWorkOrderDetail(content, parseInt(id));
      if (base === '/customers')   return await renderCustomerDetail(content, parseInt(id));
      if (base === '/vehicles')    return await renderVehicleDetail(content, parseInt(id));
    }

    if (path === '/work-orders/new') return await renderNewWorkOrder(content, params);
    if (path === '/vehicles/new')    return await renderVehicles(content, params);
    if (path === '/customers/new')   return await renderCustomers(content);

    const map = {
      '/dashboard':     renderDashboard,
      '/work-orders':   renderWorkOrders,
      '/customers':     renderCustomers,
      '/vehicles':      renderVehicles,
      '/articles':      renderArticles,
      '/pick-lists':    renderPickLists,
      '/scanner':       renderScanner,
      '/time-entries':  renderTimeEntries,
      '/calendar':      renderCalendar,
      '/users':         renderUsers,
      '/settings':      renderSettings,
    };

    const fn = map[path] || map['/dashboard'];
    await fn(content, params);
  } catch (err) {
    console.error(err);
    content.innerHTML = `<div class="alert alert-error">Fel: ${err.message}</div>`;
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────────

function showLogin() {
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
}

function showApp(user) {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('user-name').textContent = user.full_name;
  document.getElementById('user-avatar').textContent = user.full_name.charAt(0).toUpperCase();
  const roleLabels = { admin: 'Administratör', tekniker: 'Tekniker' };
  document.getElementById('user-role').textContent = roleLabels[user.role] || user.role;
  if (user.role === 'admin') {
    document.querySelectorAll('.admin-only').forEach(el => el.classList.remove('hidden'));
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('hidden'));
  } else {
    // Tekniker: show only the scanner in the sidebar
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('hidden', el.dataset.page !== 'scanner');
    });
  }
}

function landingRoute(user) {
  return user.role === 'admin' ? '#/dashboard' : '#/scanner';
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Login form
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    const btn = document.getElementById('login-btn');
    errEl.classList.add('hidden');
    btn.disabled = true;
    btn.textContent = 'Loggar in…';
    try {
      const result = await api.post('/auth/login', { email, password });
      localStorage.setItem('flow_token', result.access_token);
      localStorage.setItem('flow_user', JSON.stringify(result.user));
      showApp(result.user);
      window.location.hash = landingRoute(result.user);
      route();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Logga in';
    }
  });

  // Logout
  document.getElementById('logout-btn').addEventListener('click', () => {
    localStorage.removeItem('flow_token');
    localStorage.removeItem('flow_user');
    showLogin();
  });

  // Token expired / unauthorized
  window.addEventListener('flow:unauthorized', () => showLogin());

  // Check existing session
  const token = localStorage.getItem('flow_token');
  const userJson = localStorage.getItem('flow_user');
  if (token && userJson) {
    try {
      const user = await api.get('/users/me');
      localStorage.setItem('flow_user', JSON.stringify(user));
      showApp(user);
      route();
    } catch {
      showLogin();
    }
  } else {
    showLogin();
  }

  window.addEventListener('hashchange', route);

  // Make closeModal global for inline onclick handlers
  window.closeModal = (await import('./components/modal.js')).closeModal;
});
