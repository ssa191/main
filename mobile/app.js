'use strict';

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const num = (id) => {
  const v = parseFloat(($(id).value || '').toString().replace(/,/g, ''));
  return Number.isFinite(v) ? v : NaN;
};
const fmt = (n, dp = 2) =>
  Number.isFinite(n)
    ? n.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })
    : '—';
const pct = (n, dp = 2) => (Number.isFinite(n) ? fmt(n * 100, dp) + '%' : '—');

function render(container, rows) {
  const el = typeof container === 'string' ? $(container) : container;
  el.innerHTML = rows
    .map(
      (r) =>
        `<div class="result ${r.cls || ''}"><span class="k">${r.k}</span><span class="v">${r.v}</span></div>`
    )
    .join('');
}

/* ---------- tab navigation ---------- */
const tabbar = $('tabbar');
tabbar.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-tab]');
  if (!btn) return;
  const tab = btn.dataset.tab;
  [...tabbar.children].forEach((b) => b.classList.toggle('active', b === btn));
  document.querySelectorAll('.view').forEach((v) => (v.hidden = v.dataset.view !== tab));
  try { localStorage.setItem('pf_tab', tab); } catch (_) {}
  window.scrollTo({ top: 0 });
});

/* ---------- 1. Returns / CAGR ---------- */
function calcReturns() {
  const i = num('ret_initial'), f = num('ret_final'), y = num('ret_years');
  if (!Number.isFinite(i) || !Number.isFinite(f) || i === 0) return render('ret_out', []);
  const total = f / i - 1;
  const rows = [
    { k: 'Total return', v: pct(total), cls: total < 0 ? 'neg' : '' },
    { k: 'Absolute gain', v: fmt(f - i), cls: f - i < 0 ? 'neg' : '' },
    { k: 'Multiple (MOIC)', v: fmt(f / i, 2) + '×' },
  ];
  if (Number.isFinite(y) && y > 0 && f / i > 0) {
    const cagr = Math.pow(f / i, 1 / y) - 1;
    rows.unshift({ k: `CAGR (${fmt(y, y % 1 ? 1 : 0)} yr)`, v: pct(cagr), cls: 'primary' });
  }
  render('ret_out', rows);
}
['ret_initial', 'ret_final', 'ret_years'].forEach((id) => $(id).addEventListener('input', calcReturns));

/* ---------- 2. IRR / NPV ---------- */
const cfRows = $('cf_rows');
function cfRowTemplate(idx, value) {
  const div = document.createElement('div');
  div.className = 'cf-row';
  div.innerHTML = `<span class="per">t = ${idx}</span>
    <input type="number" inputmode="decimal" class="cf-input" placeholder="0" value="${value ?? ''}" />
    <button class="del" title="remove">×</button>`;
  div.querySelector('.cf-input').addEventListener('input', calcIRR);
  div.querySelector('.del').addEventListener('click', () => {
    if (cfRows.children.length <= 2) return;
    div.remove();
    relabelCF();
    calcIRR();
  });
  return div;
}
function relabelCF() {
  [...cfRows.children].forEach((r, i) => (r.querySelector('.per').textContent = `t = ${i}`));
}
function seedCF(values) {
  cfRows.innerHTML = '';
  values.forEach((v, i) => cfRows.appendChild(cfRowTemplate(i, v)));
}
function readCF() {
  return [...cfRows.querySelectorAll('.cf-input')].map((el) => {
    const v = parseFloat((el.value || '').replace(/,/g, ''));
    return Number.isFinite(v) ? v : 0;
  });
}
function npv(rate, cf) {
  return cf.reduce((acc, c, t) => acc + c / Math.pow(1 + rate, t), 0);
}
function irr(cf) {
  // Sign change required for a meaningful IRR
  const hasPos = cf.some((c) => c > 0), hasNeg = cf.some((c) => c < 0);
  if (!hasPos || !hasNeg) return NaN;
  // Bisection on a wide bracket — robust for conventional cash flows
  let lo = -0.9999, hi = 10;
  let fLo = npv(lo, cf), fHi = npv(hi, cf);
  if (fLo * fHi > 0) {
    // widen high end
    hi = 100; fHi = npv(hi, cf);
    if (fLo * fHi > 0) return NaN;
  }
  for (let k = 0; k < 200; k++) {
    const mid = (lo + hi) / 2;
    const fMid = npv(mid, cf);
    if (Math.abs(fMid) < 1e-7) return mid;
    if (fLo * fMid < 0) { hi = mid; fHi = fMid; } else { lo = mid; fLo = fMid; }
  }
  return (lo + hi) / 2;
}
function calcIRR() {
  const cf = readCF();
  const rate = num('irr_rate');
  const r = irr(cf);
  const rows = [];
  rows.push({ k: 'IRR (per period)', v: Number.isFinite(r) ? pct(r) : 'n/a', cls: 'primary' });
  if (Number.isFinite(rate)) {
    const n = npv(rate / 100, cf);
    rows.push({ k: `NPV @ ${fmt(rate, rate % 1 ? 2 : 0)}%`, v: fmt(n), cls: n < 0 ? 'neg' : '' });
  }
  const sum = cf.reduce((a, b) => a + b, 0);
  rows.push({ k: 'Undiscounted total', v: fmt(sum), cls: sum < 0 ? 'neg' : '' });
  render('irr_out', rows);
}
$('cf_add').addEventListener('click', () => {
  cfRows.appendChild(cfRowTemplate(cfRows.children.length));
  calcIRR();
});
$('cf_reset').addEventListener('click', () => {
  seedCF([-100000, 30000, 35000, 40000, 45000]);
  $('irr_rate').value = '10';
  calcIRR();
});
seedCF([-100000, 30000, 35000, 40000, 45000]);
$('irr_rate').value = '10';

/* ---------- 3. Loan / amortisation ---------- */
function calcLoan() {
  const P = num('loan_principal'), rAnnual = num('loan_rate'), years = num('loan_years');
  if (!(P > 0) || !(years > 0) || !Number.isFinite(rAnnual)) {
    render('loan_out', []); $('loan_schedule').innerHTML = ''; return;
  }
  const n = Math.round(years * 12);
  const i = rAnnual / 100 / 12;
  const pay = i === 0 ? P / n : (P * i) / (1 - Math.pow(1 + i, -n));
  const totalPaid = pay * n;
  render('loan_out', [
    { k: 'Monthly payment', v: fmt(pay), cls: 'primary' },
    { k: `Total paid (${n} mo)`, v: fmt(totalPaid) },
    { k: 'Total interest', v: fmt(totalPaid - P) },
  ]);
  buildSchedule(P, i, pay, n);
}
function buildSchedule(P, i, pay, n) {
  let bal = P;
  const rowsYear = [];
  let yInt = 0, yPrin = 0;
  for (let m = 1; m <= n; m++) {
    const interest = bal * i;
    let principal = pay - interest;
    if (m === n) principal = bal; // clear rounding residue on last payment
    bal = Math.max(0, bal - principal);
    yInt += interest; yPrin += principal;
    if (m % 12 === 0 || m === n) {
      rowsYear.push({ yr: Math.ceil(m / 12), prin: yPrin, int: yInt, bal });
      yInt = 0; yPrin = 0;
    }
  }
  const html = `<table><thead><tr><th>Yr</th><th>Principal</th><th>Interest</th><th>Balance</th></tr></thead>
    <tbody>${rowsYear
      .map((r) => `<tr><td>${r.yr}</td><td>${fmt(r.prin, 0)}</td><td>${fmt(r.int, 0)}</td><td>${fmt(r.bal, 0)}</td></tr>`)
      .join('')}</tbody></table>`;
  $('loan_schedule').innerHTML = html;
}
['loan_principal', 'loan_rate', 'loan_years'].forEach((id) => $(id).addEventListener('input', calcLoan));
$('loan_toggle').addEventListener('click', () => {
  const s = $('loan_schedule');
  s.hidden = !s.hidden;
  $('loan_toggle').textContent = s.hidden ? 'Show amortisation schedule' : 'Hide amortisation schedule';
});

/* ---------- 4. VAT / Zakat ---------- */
let vatMode = 'add';
document.querySelectorAll('[data-vatmode]').forEach((b) =>
  b.addEventListener('click', () => {
    vatMode = b.dataset.vatmode;
    document.querySelectorAll('[data-vatmode]').forEach((x) => x.classList.toggle('active', x === b));
    calcTax();
  })
);
function calcTax() {
  const amt = num('tax_amount'), vr = num('tax_vat') / 100, zr = num('tax_zakat') / 100;
  if (!Number.isFinite(amt)) return render('tax_out', []);
  let net, vat, gross;
  if (vatMode === 'add') { net = amt; vat = amt * vr; gross = amt + vat; }
  else { gross = amt; net = amt / (1 + vr); vat = gross - net; }
  const zakat = Number.isFinite(zr) ? net * zr : NaN;
  render('tax_out', [
    { k: 'Net (excl. VAT)', v: fmt(net) },
    { k: `VAT (${fmt(vr * 100, vr * 100 % 1 ? 1 : 0)}%)`, v: fmt(vat), cls: 'primary' },
    { k: 'Gross (incl. VAT)', v: fmt(gross), cls: 'primary' },
    { k: `Zakat on net (${fmt(zr * 100, 2)}%)`, v: fmt(zakat) },
  ]);
}
['tax_amount', 'tax_vat', 'tax_zakat'].forEach((id) => $(id).addEventListener('input', calcTax));

/* ---------- 5. Margin / Markup ---------- */
function calcMargin() {
  let cost = num('mg_cost'), price = num('mg_price'), margin = num('mg_margin') / 100;
  const have = [Number.isFinite(cost), Number.isFinite(price), Number.isFinite(margin)];
  // Derive the missing one from any two
  if (have[0] && have[1]) {
    margin = price === 0 ? NaN : (price - cost) / price;
  } else if (have[0] && have[2]) {
    if (margin >= 1) return render('mg_out', [{ k: 'Margin must be < 100%', v: '—', cls: 'neg' }]);
    price = cost / (1 - margin);
  } else if (have[1] && have[2]) {
    cost = price * (1 - margin);
  } else {
    return render('mg_out', []);
  }
  const profit = price - cost;
  const markup = cost === 0 ? NaN : profit / cost;
  render('mg_out', [
    { k: 'Cost', v: fmt(cost) },
    { k: 'Sale price', v: fmt(price) },
    { k: 'Profit per unit', v: fmt(profit), cls: profit < 0 ? 'neg' : '' },
    { k: 'Gross margin', v: pct(margin), cls: 'primary' },
    { k: 'Markup on cost', v: pct(markup) },
  ]);
}
['mg_cost', 'mg_price', 'mg_margin'].forEach((id) => $(id).addEventListener('input', calcMargin));

/* ---------- 6. FX converter ---------- */
const DEFAULT_RATES = {
  USD: 1, SAR: 3.75, AED: 3.6725, EUR: 0.92, GBP: 0.79,
  EGP: 49.5, INR: 83.3, JPY: 157, CNY: 7.24, KWD: 0.307,
};
const RATE_ORDER = Object.keys(DEFAULT_RATES);
let rates = loadRates();
function loadRates() {
  try {
    const saved = JSON.parse(localStorage.getItem('pf_rates') || 'null');
    if (saved && typeof saved === 'object') return { ...DEFAULT_RATES, ...saved };
  } catch (_) {}
  return { ...DEFAULT_RATES };
}
function saveRates() {
  try { localStorage.setItem('pf_rates', JSON.stringify(rates)); } catch (_) {}
}
function fillSelect(sel, val) {
  sel.innerHTML = RATE_ORDER.map((c) => `<option value="${c}">${c}</option>`).join('');
  sel.value = val;
}
function calcFX() {
  const amt = num('fx_amount');
  const from = $('fx_from').value, to = $('fx_to').value;
  if (!Number.isFinite(amt) || !rates[from] || !rates[to]) return render('fx_out', []);
  const usd = amt / rates[from];
  const out = usd * rates[to];
  const cross = rates[to] / rates[from];
  render('fx_out', [
    { k: `${fmt(amt)} ${from} =`, v: `${fmt(out)} ${to}`, cls: 'primary' },
    { k: `1 ${from}`, v: `${fmt(cross, 4)} ${to}` },
    { k: `1 ${to}`, v: `${fmt(1 / cross, 4)} ${from}` },
  ]);
}
function buildRateEditor() {
  $('fx_rates').innerHTML = RATE_ORDER.map(
    (c) =>
      `<div class="rate-row"><span class="code">${c}</span>
       <input type="number" inputmode="decimal" data-code="${c}" value="${rates[c]}" ${c === 'USD' ? 'disabled' : ''} /></div>`
  ).join('');
  $('fx_rates').querySelectorAll('input[data-code]').forEach((inp) =>
    inp.addEventListener('input', () => {
      const v = parseFloat(inp.value);
      if (v > 0) { rates[inp.dataset.code] = v; saveRates(); calcFX(); }
    })
  );
}
fillSelect($('fx_from'), 'USD');
fillSelect($('fx_to'), 'SAR');
buildRateEditor();
['fx_amount'].forEach((id) => $(id).addEventListener('input', calcFX));
$('fx_from').addEventListener('change', calcFX);
$('fx_to').addEventListener('change', calcFX);
$('fx_swap').addEventListener('click', () => {
  const a = $('fx_from').value; $('fx_from').value = $('fx_to').value; $('fx_to').value = a;
  calcFX();
});
$('fx_reset_rates').addEventListener('click', () => {
  rates = { ...DEFAULT_RATES }; saveRates(); buildRateEditor(); calcFX();
});

/* ---------- PWA install prompt ---------- */
let deferredPrompt = null;
const installBtn = $('installBtn');
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  installBtn.hidden = false;
});
installBtn.addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  installBtn.hidden = true;
});
window.addEventListener('appinstalled', () => (installBtn.hidden = true));

/* ---------- service worker ---------- */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}

/* ---------- restore last tab & first paint ---------- */
(function init() {
  let tab = 'returns';
  try { tab = localStorage.getItem('pf_tab') || 'returns'; } catch (_) {}
  const btn = tabbar.querySelector(`[data-tab="${tab}"]`);
  if (btn) btn.click();
  calcReturns(); calcIRR(); calcLoan(); calcTax(); calcMargin(); calcFX();
})();
