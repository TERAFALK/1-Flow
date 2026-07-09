import { api, downloadFile } from '../api.js';
import { fmtDate, statusBadge } from '../app.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderVehicles(el, params = {}) {
  let allRows = [];
  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <button class="btn btn-primary btn-sm" id="new-vehicle-btn">
      <svg viewBox="0 0 20 20" fill="currentColor" style="width:14px;height:14px"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
      Nytt fordon
    </button>`;

  el.innerHTML = `
    <div class="page-title" style="margin-bottom:4px">Fordon</div>
    <div class="page-subtitle" style="margin-bottom:20px">Fordonsregister</div>
    <div class="card">
      <div class="card-header">
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="vehicle-search" placeholder="Sök reg.nr…">
        </div>
      </div>
      <div id="vehicle-list"><div class="loading">Laddar…</div></div>
    </div>
  `;

  document.getElementById('new-vehicle-btn')?.addEventListener('click', () =>
    openVehicleForm(null, params.customer_id || null, reload)
  );

  let timer;
  document.getElementById('vehicle-search').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => loadList(e.target.value), 300);
  });

  async function loadList(q = '') {
    const list = document.getElementById('vehicle-list');
    if (!list) return;
    const vehicles = await api.get(`/vehicles${q ? `?q=${encodeURIComponent(q)}` : ''}`);
    allRows = vehicles;
    if (!vehicles.length) {
      list.innerHTML = `<div class="empty-state"><p>Inga fordon hittade</p></div>`;
      return;
    }
    list.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Reg.nr</th><th>Märke / Modell</th><th>År</th><th>Kund</th><th>Mätarst.</th><th></th></tr></thead>
          <tbody>
            ${vehicles.map(v => `
              <tr class="clickable" onclick="location.hash='#/vehicles/${v.id}'">
                <td><strong>${v.license_plate}</strong></td>
                <td>${v.make || ''} ${v.model || ''}</td>
                <td>${v.year || '–'}</td>
                <td>${v.customer?.name || '–'}</td>
                <td>${v.odometer ? v.odometer.toLocaleString('sv-SE') + ' km' : '–'}</td>
                <td onclick="event.stopPropagation()">
                  <div class="flex gap-2">
                    <button type="button" class="btn-icon" title="Redigera" onclick="window._editVehicle(${v.id})">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                    </button>
                    <button type="button" class="btn-icon" title="Ta bort" onclick="window._deleteVehicle(${v.id})">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function reload() { loadList(document.getElementById('vehicle-search')?.value || ''); }

  window._editVehicle = async (id) => {
    const v = await api.get(`/vehicles/${id}`);
    openVehicleForm(v, null, reload);
  };
  window._deleteVehicle = async (id) => {
    const v = allRows.find(x => x.id === id);
    const plate = (v?.license_plate || 'fordonet').replace(/</g, '&lt;');
    if (await confirmDialog(`Ta bort fordonet <strong>${plate}</strong>?`)) {
      try {
        await api.delete(`/vehicles/${id}`);
        showToast('Fordon borttaget', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    }
  };

  await loadList();
}

export async function renderVehicleDetail(el, id) {
  el.innerHTML = '<div class="loading">Laddar…</div>';

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <a href="#/vehicles" class="btn btn-secondary btn-sm">← Tillbaka</a>
    <button class="btn btn-secondary btn-sm" id="topbar-edit-vehicle">Redigera</button>`;

  const [v, orders] = await Promise.all([
    api.get(`/vehicles/${id}`),
    api.get('/work-orders').then(all => all.filter(o => o.vehicle_id == id)).catch(() => []),
  ]);

  if (document.getElementById('topbar-title'))
    document.getElementById('topbar-title').textContent = v.license_plate;

  document.getElementById('topbar-edit-vehicle')?.addEventListener('click', () =>
    openVehicleForm(v, null, () => renderVehicleDetail(el, id))
  );

  el.innerHTML = `
    <div style="margin-bottom:20px">
      <div class="page-title">${v.license_plate}</div>
      <div class="page-subtitle">${[v.make, v.model, v.year ? `(${v.year})` : ''].filter(Boolean).join(' ')}</div>
    </div>

    <div class="tabs" id="vehicle-tabs">
      <div class="tab active" data-tab="info">Info</div>
      <div class="tab" data-tab="turning">Svängradie</div>
      <div class="tab" data-tab="axleload">Axeltryck</div>
      <div class="tab" data-tab="history">Historik <span style="font-size:11px;opacity:.6">(${orders.length})</span></div>
    </div>

    <div id="tab-info">
      <div style="display:grid;grid-template-columns:300px 1fr;gap:16px">
        <div class="card">
          <div class="card-header"><span class="card-title">Fordonsdata</span></div>
          <div class="card-body">
            ${v.customer ? metaRow('Kund', `<a href="#/customers/${v.customer_id}" style="color:var(--accent)">${v.customer.name}</a>`) : ''}
            ${metaRow('Regnummer', v.license_plate)}
            ${metaRow('Chassinr (VIN)', v.vin)}
            ${metaRow('Märke', v.make)}
            ${metaRow('Modell', v.model)}
            ${metaRow('Årsmodell', v.year)}
            ${metaRow('Motor', v.engine)}
            ${metaRow('Växellåda', v.gearbox)}
            ${metaRow('Mätarst.', v.odometer ? v.odometer.toLocaleString('sv-SE') + ' km' : null)}
            ${metaRow('Kraftuttag', v.kraftuttag)}
            ${metaRow('Utväxling', v.utvaxling)}
            ${metaRow('Rotation', v.rotation)}
            ${metaRow('Medbringare', v.medbringare)}
            ${metaRow('Hjulbas', v.wheelbase_mm ? v.wheelbase_mm + ' mm' : null)}
            ${metaRow('Bredd', v.width_mm ? v.width_mm + ' mm' : null)}
            ${v.notes ? `<hr class="divider"><p style="font-size:13px;color:var(--text-2)">${v.notes}</p>` : ''}
          </div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">Senaste arbetsorder</span></div>
          ${renderOrderTable(orders.slice(0, 5))}
        </div>
      </div>
    </div>

    <div id="tab-turning" class="hidden">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Svängradie</span>
          <div style="display:flex;gap:8px;align-items:center">
            <label style="font-size:12px;color:var(--text-3)">Styrvinkel</label>
            <input type="number" id="turn-angle" value="${v.max_steering_angle || 20}" step="0.5" min="1" max="89" style="width:70px">
            <span style="font-size:12px;color:var(--text-3)">°</span>
            <button class="btn btn-ghost btn-sm" id="turn-pdf-btn">
              <svg viewBox="0 0 20 20" fill="currentColor" style="width:14px;height:14px"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM9.293 13.707a1 1 0 001.414 0l4-4a1 1 0 00-1.414-1.414L11 10.586V3a1 1 0 10-2 0v7.586L6.707 8.293a1 1 0 00-1.414 1.414l4 4z" clip-rule="evenodd"/></svg>
              Ladda ner PDF (liggande)
            </button>
          </div>
        </div>
        <div class="card-body" id="turn-body"><div class="loading">Laddar…</div></div>
      </div>
    </div>

    <div id="tab-axleload" class="hidden">
      <div class="card">
        <div class="card-header"><span class="card-title">Axeltryck – tankplacering</span></div>
        <div class="card-body" id="axleload-body"></div>
      </div>
    </div>

    <div id="tab-history" class="hidden">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Arbetsorder-historik</span>
          <a href="#/work-orders/new?vehicle=${v.id}&customer=${v.customer_id}" class="btn btn-primary btn-sm">Ny arbetsorder</a>
        </div>
        ${renderOrderTable(orders)}
      </div>
    </div>
  `;

  let turningLoaded = false, axleLoaded = false;
  document.getElementById('vehicle-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    document.querySelectorAll('#vehicle-tabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    ['info', 'turning', 'axleload', 'history'].forEach(name => {
      document.getElementById(`tab-${name}`).classList.toggle('hidden', name !== tab.dataset.tab);
    });
    if (tab.dataset.tab === 'turning' && !turningLoaded) { turningLoaded = true; loadTurning(v); }
    if (tab.dataset.tab === 'axleload' && !axleLoaded) { axleLoaded = true; loadAxleLoad(v); }
  });
}

function loadAxleLoad(v) {
  const el = document.getElementById('axleload-body');
  const F = (id, label, ph = '') => `<div class="field"><label>${label}</label><input type="number" id="${id}" placeholder="${ph}"></div>`;
  el.innerHTML = `
    <div style="display:grid;grid-template-columns:300px 1fr;gap:24px;align-items:start">
      <div>
        <div class="text-muted" style="font-size:12px;margin-bottom:6px">Max tillåtet axeltryck</div>
        <div class="form-row">${F('al-mf', 'Max fram (kg)')}${F('al-mr', 'Max bak (kg)')}</div>

        <div class="text-muted" style="font-size:12px;margin:10px 0 6px">Tomvikt (tomt chassi)</div>
        <div class="form-row">${F('al-ef', 'Tomvikt fram (kg)')}${F('al-er', 'Tomvikt bak (kg)')}</div>
        <div class="form-row">${F('al-et', 'Total tomvikt (kg)')}${F('al-tl', 'Tanklängd (mm)', 't.ex. 6000')}</div>

        <div class="text-muted" style="font-size:12px;margin:10px 0 6px">Önskat / lastat</div>
        <div class="form-row">${F('al-df', 'Önskat fram (kg)')}${F('al-dr', 'Önskat bak (kg)')}</div>
        <div class="field"><label>Totalvikt lastad (kg)</label><input type="number" id="al-lt" placeholder="hela fordonet med tank"></div>

        <div class="text-muted" style="font-size:11px;margin-bottom:8px">Hjulbas hämtas från fordonet (${v.wheelbase_mm ? v.wheelbase_mm + ' mm' : 'ej ifylld – fyll i under Redigera'}).</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-primary btn-sm" id="al-save-btn">Spara indata</button>
          <button class="btn btn-ghost btn-sm" id="al-pdf-btn">
            <svg viewBox="0 0 20 20" fill="currentColor" style="width:14px;height:14px"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM9.293 13.707a1 1 0 001.414 0l4-4a1 1 0 00-1.414-1.414L11 10.586V3a1 1 0 10-2 0v7.586L6.707 8.293a1 1 0 00-1.414 1.414l4 4z" clip-rule="evenodd"/></svg>
            Ladda ner PDF
          </button>
        </div>
      </div>
      <div id="al-result"><div class="text-muted" style="font-size:13px">Fyll i värdena så beräknas axeltrycken och tankens placering.</div></div>
    </div>`;

  const fields = {
    max_front: 'al-mf', max_rear: 'al-mr', empty_front: 'al-ef', empty_rear: 'al-er',
    empty_total: 'al-et', tank_length: 'al-tl', desired_front: 'al-df', desired_rear: 'al-dr',
    loaded_total: 'al-lt',
  };

  // Förifyll från sparad indata
  const saved = v.axle_load || {};
  for (const [k, id] of Object.entries(fields)) {
    if (saved[k] !== null && saved[k] !== undefined) document.getElementById(id).value = saved[k];
  }

  function params() {
    const p = {};
    for (const [k, id] of Object.entries(fields)) {
      const x = parseFloat(document.getElementById(id).value);
      p[k] = isNaN(x) ? null : x;
    }
    return p;
  }
  const query = p => Object.entries(p).filter(([, x]) => x !== null)
    .map(([k, x]) => `${k}=${encodeURIComponent(x)}`).join('&');

  async function recompute() {
    const p = params();
    if (Object.values(p).some(x => x === null)) return;
    const box = document.getElementById('al-result');
    let r;
    try { r = await api.get(`/vehicles/${v.id}/axle-load?${query(p)}`); }
    catch (err) { box.innerHTML = `<div class="alert alert-warning" style="margin:0">${err.message}</div>`; return; }
    const kg = x => Math.round(x).toLocaleString('sv-SE') + ' kg';
    const util = (u) => `<span style="color:${u > 100 ? '#e5484d' : '#12a150'};font-weight:700">${u}%</span>`;
    box.innerHTML = `
      <div class="table-wrap" style="margin-bottom:16px">
        <table>
          <thead><tr><th></th><th class="text-right">Fram</th><th class="text-right">Bak</th><th class="text-right">Totalt</th></tr></thead>
          <tbody>
            <tr><td>Tomvikt</td><td class="text-right">${kg(r.empty_front)}</td><td class="text-right">${kg(r.empty_rear)}</td><td class="text-right">${kg(r.empty_total)}</td></tr>
            <tr><td><strong>Lastad</strong></td><td class="text-right"><strong>${kg(r.load_front)}</strong></td><td class="text-right"><strong>${kg(r.load_rear)}</strong></td><td class="text-right"><strong>${kg(r.loaded_total)}</strong></td></tr>
            <tr><td>Max tillåten</td><td class="text-right">${kg(r.max_front)}</td><td class="text-right">${kg(r.max_rear)}</td><td class="text-right">${kg(r.max_total)}</td></tr>
            <tr><td>Utnyttjande</td><td class="text-right">${util(r.front_util)}</td><td class="text-right">${util(r.rear_util)}</td><td class="text-right">${util(r.total_util)}</td></tr>
          </tbody>
        </table>
      </div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px">
        ${turnStat('Tankvikt', r.tank_weight, null, ' kg')}
        ${turnStat('TP från andra axeln', r.cg_axle2, 'var(--accent)', ' mm')}
        ${turnStat('TP bakom framaxel', r.cg, null, ' mm')}
        ${turnStat('Tankens framkant', r.tank_front, null, ' mm')}
      </div>
      ${r.warnings && r.warnings.length ? `<div class="alert alert-warning" style="margin:0 0 12px">${r.warnings.map(w => `⚠ ${w}`).join('<br>')}</div>` : ''}
      <div style="overflow-x:auto">${axleSvg(r)}</div>`;
  }

  Object.values(fields).forEach(id => document.getElementById(id).addEventListener('input', recompute));
  document.getElementById('al-pdf-btn').addEventListener('click', async () => {
    const p = params();
    if (Object.values(p).some(x => x === null)) { showToast('Fyll i alla fält först', 'error'); return; }
    try { await downloadFile(`/vehicles/${v.id}/axle-load/pdf?${query(p)}`, `axeltryck-${v.license_plate}.pdf`); }
    catch (err) { showToast(err.message, 'error'); }
  });
  document.getElementById('al-save-btn').addEventListener('click', async () => {
    try {
      const data = params();
      await api.put(`/vehicles/${v.id}`, { axle_load: data });
      v.axle_load = data;
      showToast('Indata sparad', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  if (Object.values(params()).every(x => x !== null)) recompute();
}

function axleSvg(r) {
  // Sidvy med lastbilssiluett. Siluettpunkterna kommer från servern (mm, y uppåt).
  const sil = r.silhouette || {};
  const rW = sil.wheel_r || 520;
  const beamBot = sil.beam_bot || 640, beamTop = sil.beam_top || 820;
  const tankBot = sil.tank_bot || (beamTop + 40), tankTop = sil.tank_top || (tankBot + 2000);
  const axles = (r.axle_offsets && r.axle_offsets.length >= 2) ? r.axle_offsets : [0, r.wheelbase];
  const rearRef = r.wheelbase;
  const dims = r.dimensions || [];
  const dimYs = dims.map(d => d.y);
  const cabFront = sil.cab ? sil.cab[0][0] : Math.min(0, ...axles) - 1400;
  const cabTop = sil.cab ? Math.max(...sil.cab.map(p => p[1])) : tankTop;
  const W = 680, H = 340;
  const x0 = Math.min(0, r.tank_front, cabFront, ...axles) - 700;
  const x1 = Math.max(rearRef, r.tank_front + r.tank_length, ...axles) + 900;
  const y0 = Math.min(-900, ...dimYs) - 60;
  const y1 = Math.max(cabTop + 250, tankTop, ...dimYs) + 160;
  const s = Math.min((W - 20) / (x1 - x0), (H - 20) / (y1 - y0));
  const ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
  const T = (x, y) => [ox + (x - x0) * s, H - (oy + (y - y0) * s)];
  const P = pts => pts.map(p => T(p[0], p[1]).join(',')).join(' ');
  const gy = T(x0, 0)[1];
  const [bx0, by0] = T(Math.min(...axles) - rW, beamTop), [bx1] = T(Math.max(...axles) + rW, beamBot);
  const [tx0, ty0] = T(r.tank_front, tankTop), [tx1, ty1] = T(r.tank_front + r.tank_length, tankBot);
  const wheel = ax => { const [cx, cy] = T(ax, rW); return `<circle cx="${cx}" cy="${cy}" r="${rW * s}" fill="#1f2937"/><circle cx="${cx}" cy="${cy}" r="${rW * s * 0.4}" fill="#9aa6b2"/>`; };
  const cgTop = T(r.cg, tankTop + 500), cgBot = T(r.cg, beamTop);
  const axleLabel = (ax, name, load) => { const [lx] = T(ax, 0); const ly = T(ax, -150)[1], ly2 = T(ax, -320)[1];
    return `<text x="${lx}" y="${ly}" text-anchor="middle" font-size="11" font-weight="700" fill="var(--text-2)">${name}</text>
            <text x="${lx}" y="${ly2}" text-anchor="middle" font-size="10" fill="#e5484d">${Math.round(load).toLocaleString('sv-SE')} kg</text>`; };
  const baffles = (sil.baffles || []).map(b => {
    const a = T(b[0][0], b[0][1]), z = T(b[1][0], b[1][1]);
    return `<line x1="${a[0]}" y1="${a[1]}" x2="${z[0]}" y2="${z[1]}" stroke="var(--accent)" stroke-width="0.8" opacity="0.6"/>`;
  }).join('');
  const fenders = (sil.fenders || []).map(f => `<polyline points="${P(f)}" fill="none" stroke="#374151" stroke-width="2"/>`).join('');
  const dimSvg = dims.map(d => {
    const a = T(d.a, d.y), b = T(d.b, d.y), col = d.accent ? '#e5484d' : '#5a6675';
    return `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${col}" stroke-width="0.8"/>
      <line x1="${a[0]}" y1="${a[1] - 4}" x2="${a[0]}" y2="${a[1] + 4}" stroke="${col}" stroke-width="0.8"/>
      <line x1="${b[0]}" y1="${b[1] - 4}" x2="${b[0]}" y2="${b[1] + 4}" stroke="${col}" stroke-width="0.8"/>
      <text x="${(a[0] + b[0]) / 2}" y="${a[1] - 3}" text-anchor="middle" font-size="9" fill="${col}">${d.label}</text>`;
  }).join('');
  const wt = T(r.cg, tankTop + 560);
  return `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;height:auto" font-family="inherit">
      <line x1="${T(x0, 0)[0]}" y1="${gy}" x2="${T(x1, 0)[0]}" y2="${gy}" stroke="#c3ccd6" stroke-width="1"/>
      <rect x="${bx0}" y="${by0}" width="${bx1 - bx0}" height="${T(0, beamBot)[1] - by0}" fill="#94a3b8"/>
      <rect x="${tx0}" y="${ty0}" width="${tx1 - tx0}" height="${ty1 - ty0}" rx="10" fill="var(--accent)" fill-opacity="0.18" stroke="var(--accent)" stroke-width="1.6"/>
      ${baffles}
      ${axles.map(wheel).join('')}
      ${fenders}
      ${sil.cab ? `<polygon points="${P(sil.cab)}" fill="#cbd5e1" stroke="#475569" stroke-width="1.4"/>` : ''}
      ${sil.windshield ? `<polygon points="${P(sil.windshield)}" fill="#7dd3fc" fill-opacity="0.55"/>` : ''}
      ${sil.bumper ? `<polygon points="${P(sil.bumper)}" fill="#475569"/>` : ''}
      <line x1="${cgBot[0]}" y1="${cgBot[1]}" x2="${cgTop[0]}" y2="${cgTop[1]}" stroke="#e5484d" stroke-width="1.4" stroke-dasharray="4 3"/>
      <circle cx="${cgTop[0]}" cy="${cgTop[1]}" r="4" fill="#e5484d"/>
      <text x="${cgTop[0] + 6}" y="${cgTop[1] + 3}" font-size="9" font-weight="700" fill="#e5484d">TP</text>
      <text x="${wt[0]}" y="${wt[1]}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e5484d">${Math.round(r.tank_weight).toLocaleString('sv-SE')} kg</text>
      ${dimSvg}
      ${axleLabel(0, 'Framaxel', r.load_front)} ${axleLabel(rearRef, 'Bakaxel', r.load_rear)}
    </svg>`;
}

function loadTurning(v) {
  const body = document.getElementById('turn-body');
  const angleInput = document.getElementById('turn-angle');

  async function render() {
    const angle = parseFloat(angleInput.value) || 20;
    body.innerHTML = '<div class="loading">Beräknar…</div>';
    let res;
    try {
      res = await api.get(`/vehicles/${v.id}/turning?angle=${angle}`);
    } catch (err) {
      body.innerHTML = `<div class="alert alert-warning" style="margin:0">${err.message}</div>
        <div class="text-muted" style="font-size:12px;margin-top:8px">Fyll i hjulbas och bredd under Redigera för att beräkna svängradie.</div>`;
      return;
    }
    body.innerHTML = `
      <div style="display:grid;grid-template-columns:200px 1fr;gap:20px;align-items:start">
        <div>
          ${turnStat('Ytterradie R ut', res.r_out, 'var(--accent)')}
          ${turnStat('Innerradie R in', res.r_in, '#12a150')}
          ${turnStat('Framaxel R fram', res.r_front)}
          ${turnStat('Svepbredd', res.swept_width)}
          ${turnStat('Styrvinkel fram', res.steering_angle, null, '°', 1)}
          ${(res.axle_angles || []).filter((a, i) => a.steered && i > 0).map((a) =>
            turnStat(`Styrvinkel axel ${res.axle_angles.indexOf(a) + 1}`, a.angle, '#e5484d', '°', 1)).join('')}
        </div>
        <div style="min-width:0;overflow-x:auto">${turningSvg(res)}</div>
      </div>`;
  }

  angleInput.addEventListener('change', render);
  document.getElementById('turn-pdf-btn').addEventListener('click', async () => {
    const angle = parseFloat(angleInput.value) || 20;
    try {
      await downloadFile(`/vehicles/${v.id}/turning/pdf?angle=${angle}`, `svangradie-${v.license_plate}.pdf`);
    } catch (err) { showToast(err.message, 'error'); }
  });
  render();
}

function turnStat(label, value, color, unit = 'mm', dec = 0) {
  const u = unit.trim();
  const num = u === '°'
    ? Number(value).toFixed(dec) + '°'
    : Math.round(value).toLocaleString('sv-SE') + ' ' + u;
  return `<div style="margin-bottom:12px">
    <div style="font-size:12px;color:var(--text-3)">${label}</div>
    <div style="font-size:18px;font-weight:700${color ? `;color:${color}` : ''}">${num}</div>
  </div>`;
}

function turningSvg(res) {
  // Passa in alla punkter (mm, y uppåt) i en fast viewBox och flippa y.
  const W = 640, H = 380, pad = 12;
  const all = [...res.arc_in, ...res.arc_out, ...res.body, ...res.ghost, res.center];
  const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const s = Math.min((W - 2 * pad) / (maxX - minX || 1), (H - 2 * pad) / (maxY - minY || 1));
  const ox = (W - (maxX - minX) * s) / 2, oy = (H - (maxY - minY) * s) / 2;
  const T = p => [ox + (p[0] - minX) * s, H - (oy + (p[1] - minY) * s)];
  const pts = arr => arr.map(p => T(p).map(n => n.toFixed(1)).join(',')).join(' ');
  const band = [...res.arc_out, ...res.arc_in.slice().reverse()];
  const cen = T(res.center);
  const wheels = (res.wheels || []).map(w => `<polygon points="${pts(w)}" fill="#374151"/>`).join('');
  return `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;height:auto" font-family="inherit">
      <polygon points="${pts(band)}" fill="var(--accent)" opacity="0.10"/>
      <polyline points="${pts(res.arc_out)}" fill="none" stroke="var(--accent)" stroke-width="2"/>
      <polyline points="${pts(res.arc_in)}" fill="none" stroke="#12a150" stroke-width="2"/>
      <polygon points="${pts(res.ghost)}" fill="none" stroke="#9aa6b2" stroke-width="1.2" stroke-dasharray="5 4" opacity="0.8"/>
      ${wheels}
      <polygon points="${pts(res.body)}" fill="var(--accent)" fill-opacity="0.08" stroke="var(--accent)" stroke-width="2"/>
      <polygon points="${pts(res.cab)}" fill="var(--accent)" opacity="0.28" stroke="var(--accent)" stroke-width="1"/>
      <circle cx="${cen[0]}" cy="${cen[1]}" r="4" fill="#e5484d"/>
    </svg>`;
}

function renderOrderTable(orders) {
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Order</th><th>Beskrivning</th><th>Status</th><th>Datum</th></tr></thead>
        <tbody>
          ${orders.length ? orders.map(o => `
            <tr class="clickable" onclick="location.hash='#/work-orders/${o.id}'">
              <td><strong>${o.order_number}</strong></td>
              <td>${o.description}</td>
              <td>${statusBadge(o.status)}</td>
              <td class="text-muted">${fmtDate(o.created_at)}</td>
            </tr>
          `).join('') : '<tr><td colspan="4" style="text-align:center;padding:28px;color:var(--text-3)">Inga arbetsorder</td></tr>'}
        </tbody>
      </table>
    </div>`;
}

function metaRow(label, value) {
  if (!value) return '';
  return `<div class="meta-row"><span class="meta-label">${label}:</span><span>${value}</span></div>`;
}

async function openVehicleForm(vehicle, defaultCustomerId, onSaved) {
  const customers = await api.get('/customers');

  // Startvärden för axelkonfigurationen (offset i mm från främre axeln)
  const initAxles = (vehicle?.axles && vehicle.axles.length >= 2)
    ? vehicle.axles.map(a => ({ offset: a.offset_mm ?? a.offset ?? 0, steered: !!a.steered }))
    : (vehicle?.wheelbase_mm
        ? [{ offset: 0, steered: true }, { offset: vehicle.wheelbase_mm, steered: false }]
        : [{ offset: 0, steered: true }, { offset: 4000, steered: false }]);

  openModal({
    title: vehicle ? 'Redigera fordon' : 'Nytt fordon',
    size: 'modal-lg',
    body: `
      <form id="vehicle-form">
        <div class="form-row">
          <div class="field">
            <label>Kund *</label>
            <select name="customer_id" required>
              <option value="">Välj kund…</option>
              ${customers.map(c => `<option value="${c.id}" ${(vehicle?.customer_id == c.id || defaultCustomerId == c.id) ? 'selected' : ''}>${c.name}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Reg.nr *</label><input type="text" name="license_plate" value="${vehicle?.license_plate || ''}" required style="text-transform:uppercase" placeholder="ABC 123"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Chassinummer (VIN)</label><input type="text" name="vin" value="${vehicle?.vin || ''}"></div>
          <div class="field"><label>Årsmodell</label><input type="number" name="year" value="${vehicle?.year || ''}" min="1900" max="2099"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Märke</label><input type="text" name="make" value="${vehicle?.make || ''}" placeholder="t.ex. Scania"></div>
          <div class="field"><label>Modell</label><input type="text" name="model" value="${vehicle?.model || ''}" placeholder="t.ex. R500"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Motor</label><input type="text" name="engine" value="${vehicle?.engine || ''}"></div>
          <div class="field"><label>Växellåda</label><input type="text" name="gearbox" value="${vehicle?.gearbox || ''}"></div>
        </div>
        <div class="field"><label>Mätarställning (km)</label><input type="number" name="odometer" value="${vehicle?.odometer || ''}"></div>
        <div class="form-row">
          <div class="field"><label>Kraftuttag</label><input type="text" name="kraftuttag" value="${vehicle?.kraftuttag || ''}"></div>
          <div class="field"><label>Utväxling</label><input type="text" name="utvaxling" value="${vehicle?.utvaxling || ''}"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Rotation</label><input type="text" name="rotation" value="${vehicle?.rotation || ''}"></div>
          <div class="field"><label>Medbringare</label><input type="text" name="medbringare" value="${vehicle?.medbringare || ''}"></div>
        </div>

        <hr class="divider">
        <div class="text-muted" style="font-size:12px;margin-bottom:8px">Svängradiemått (för beräkning)</div>
        <div class="form-row">
          <div class="field"><label>Bredd (mm)</label><input type="number" name="width_mm" value="${vehicle?.width_mm || ''}" placeholder="t.ex. 2550"></div>
          <div class="field"><label>Max styrvinkel fram (°)</label><input type="number" name="max_steering_angle" value="${vehicle?.max_steering_angle || ''}" step="0.1" min="1" max="89" placeholder="t.ex. 20"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Framskjut (mm)</label><input type="number" name="front_overhang_mm" value="${vehicle?.front_overhang_mm || ''}" placeholder="framaxel → front"></div>
          <div class="field"><label>Bakskjut (mm)</label><input type="number" name="rear_overhang_mm" value="${vehicle?.rear_overhang_mm || ''}" placeholder="bakre axel → bak"></div>
        </div>
        <div class="field" style="max-width:200px">
          <label>Antal axlar</label>
          <select id="axle-count">${[2,3,4,5,6].map(n => `<option value="${n}" ${n === initAxles.length ? 'selected' : ''}>${n}</option>`).join('')}</select>
        </div>
        <div id="axle-rows" style="margin-bottom:4px"></div>
        <div class="text-muted" style="font-size:11px;margin-bottom:8px">Ange avstånd från föregående axel. Markera vilka axlar som är styrbara (en styrd bakre axel minskar svepbredden).</div>

        <div class="field"><label>Anteckningar</label><textarea name="notes">${vehicle?.notes || ''}</textarea></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${vehicle ? 'Spara' : 'Skapa fordon'}</button>
        </div>
      </form>
    `,
  });

  // ── Axelrader (dynamiskt utifrån antal axlar) ──
  const axleCountSel = document.getElementById('axle-count');
  function renderAxleRows(n) {
    const rows = [];
    for (let i = 0; i < n; i++) {
      const ax = initAxles[i];
      const spacing = (i > 0 && ax && initAxles[i - 1]) ? Math.max(1, ax.offset - initAxles[i - 1].offset) : (i > 0 ? 1400 : 0);
      const steered = ax ? ax.steered : false;
      rows.push(`
        <div class="form-row" style="align-items:flex-end;margin-bottom:6px">
          <div class="field" style="margin:0">
            <label>${i === 0 ? 'Axel 1 · framaxel' : 'Axel ' + (i + 1) + ' · avstånd (mm)'}</label>
            ${i === 0
              ? '<input type="text" value="0 (referens)" disabled style="opacity:.55">'
              : `<input type="number" data-spacing="${i}" value="${spacing}" min="1" placeholder="från föreg. axel">`}
          </div>
          <div class="field" style="margin:0;max-width:120px">
            <label style="font-size:12px;white-space:nowrap"><input type="checkbox" data-steered="${i}" ${steered ? 'checked' : ''}> Styrbar</label>
          </div>
        </div>`);
    }
    document.getElementById('axle-rows').innerHTML = rows.join('');
  }
  renderAxleRows(initAxles.length);
  axleCountSel.addEventListener('change', () => renderAxleRows(parseInt(axleCountSel.value)));

  document.getElementById('vehicle-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    ['year', 'odometer', 'customer_id', 'wheelbase_mm', 'width_mm', 'front_overhang_mm',
     'rear_overhang_mm', 'max_steering_angle'].forEach(k => { body[k] = body[k] ? Number(body[k]) : null; });
    Object.keys(body).forEach(k => { if (body[k] === '') body[k] = null; });

    // Bygg axelkonfigurationen från raderna
    const n = parseInt(axleCountSel.value);
    const axles = [];
    let offset = 0;
    for (let i = 0; i < n; i++) {
      if (i > 0) offset += Math.max(0, parseFloat(document.querySelector(`[data-spacing="${i}"]`)?.value) || 0);
      const steered = document.querySelector(`[data-steered="${i}"]`)?.checked || false;
      axles.push({ offset_mm: Math.round(offset), steered });
    }
    body.axles = axles;
    body.wheelbase_mm = axles[1] ? axles[1].offset_mm : null;  // bakåtkompat: hjulbas = axel 1→2
    try {
      if (vehicle) {
        await api.put(`/vehicles/${vehicle.id}`, body);
        showToast('Fordon uppdaterat', 'success');
      } else {
        await api.post('/vehicles', body);
        showToast('Fordon skapat', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}
