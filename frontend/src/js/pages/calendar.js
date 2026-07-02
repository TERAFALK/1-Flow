import { api } from '../api.js';
import { statusBadge } from '../app.js';

export async function renderCalendar(el) {
  const now = new Date();
  let year = now.getFullYear();
  let month = now.getMonth() + 1;

  async function draw() {
    const orders = await api.get(`/work-orders/calendar?year=${year}&month=${month}`);
    const ordersByDay = {};
    for (const o of orders) {
      const d = new Date(o.scheduled_date + 'Z').getDate();
      (ordersByDay[d] = ordersByDay[d] || []).push(o);
    }

    const monthNames = ['Jan','Feb','Mar','Apr','Maj','Jun','Jul','Aug','Sep','Okt','Nov','Dec'];
    const dayNames = ['Mån','Tis','Ons','Tor','Fre','Lör','Sön'];
    const firstDay = new Date(year, month - 1, 1);
    let startDow = firstDay.getDay() === 0 ? 6 : firstDay.getDay() - 1; // Mon=0
    const daysInMonth = new Date(year, month, 0).getDate();
    const today = new Date();

    let cells = '';
    let day = 1 - startDow;
    for (let row = 0; row < 6; row++) {
      const weekMondayDay = day;
      const weekMonday = new Date(year, month - 1, weekMondayDay);
      cells += `<div class="cal-week-num">${isoWeekNumber(weekMonday)}</div>`;
      for (let col = 0; col < 7; col++, day++) {
        const isOther = day < 1 || day > daysInMonth;
        const isToday = !isOther && day === today.getDate() && month === today.getMonth() + 1 && year === today.getFullYear();
        const dayOrders = (!isOther && ordersByDay[day]) || [];
        cells += `
          <div class="cal-day ${isOther ? 'other-month' : ''} ${isToday ? 'today' : ''}">
            <div class="cal-day-num">${isOther ? '' : day}</div>
            ${dayOrders.map(o => `
              <div class="cal-event ${o.status}" title="${o.order_number} – ${o.customer?.name || ''} – ${o.scheduled_date ? new Date(o.scheduled_date + 'Z').toLocaleDateString('sv-SE') : ''}" onclick="location.hash='#/work-orders/${o.id}'">
                ${o.order_number} ${o.vehicle?.license_plate || ''}
              </div>
            `).join('')}
          </div>
        `;
      }
    }

    el.innerHTML = `
      <div class="page-header">
        <div class="page-title">Kalender</div>
        <div class="flex gap-2">
          <button class="btn btn-secondary" id="cal-prev">‹ Föregående</button>
          <span style="min-width:140px;text-align:center;font-weight:600;font-size:16px;align-self:center">
            ${monthNames[month - 1]} ${year}
          </span>
          <button class="btn btn-secondary" id="cal-next">Nästa ›</button>
          <button class="btn btn-ghost" id="cal-today">Idag</button>
        </div>
      </div>
      <div class="cal-grid">
        <div class="cal-week-num" style="font-size:9px">v.</div>
        ${dayNames.map(d => `<div class="cal-head">${d}</div>`).join('')}
        ${cells}
      </div>
      <div style="margin-top:16px;display:flex;gap:16px;flex-wrap:wrap">
        <span class="cal-event ny" style="position:static;margin:0;padding:3px 10px">Ny</span>
        <span class="cal-event planerad" style="position:static;margin:0;padding:3px 10px">Planerad</span>
        <span class="cal-event pagaende" style="position:static;margin:0;padding:3px 10px">Pågående</span>
        <span class="cal-event klar" style="position:static;margin:0;padding:3px 10px">Klar</span>
      </div>
    `;

    document.getElementById('cal-prev').addEventListener('click', () => {
      month--; if (month < 1) { month = 12; year--; } draw();
    });
    document.getElementById('cal-next').addEventListener('click', () => {
      month++; if (month > 12) { month = 1; year++; } draw();
    });
    document.getElementById('cal-today').addEventListener('click', () => {
      year = now.getFullYear(); month = now.getMonth() + 1; draw();
    });
  }

  el.innerHTML = '<div class="loading">Laddar kalender…</div>';
  await draw();
}

function isoWeekNumber(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}
