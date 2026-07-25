/* Acme ERP — single-page frontend (framework-free).
 * A tiny hash router renders module "views". Every view talks to the FastAPI
 * JSON API through the api() helper, which attaches the bearer token.
 */
(() => {
  "use strict";

  const State = {
    token: localStorage.getItem("erp_token") || null,
    user: JSON.parse(localStorage.getItem("erp_user") || "null"),
    // small caches populated on demand for dropdowns
    cache: {},
  };

  // ------------------------------------------------------------------ API ---
  async function api(path, { method = "GET", body, form } = {}) {
    const headers = {};
    if (State.token) headers["Authorization"] = "Bearer " + State.token;
    let payload;
    if (form) {
      payload = new URLSearchParams(form).toString();
      headers["Content-Type"] = "application/x-www-form-urlencoded";
    } else if (body !== undefined) {
      payload = JSON.stringify(body);
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch("/api" + path, { method, headers, body: payload });
    if (res.status === 401) { logout(); throw new Error("Session expired"); }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.status === 204 ? null : res.json();
  }

  // --------------------------------------------------------------- helpers ---
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };
  const money = (n) => "$" + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function toast(msg, isErr = false) {
    const t = el(`<div class="toast ${isErr ? "err" : ""}">${esc(msg)}</div>`);
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  }

  function logout() {
    State.token = null; State.user = null;
    localStorage.removeItem("erp_token"); localStorage.removeItem("erp_user");
    location.hash = "";
    render();
  }

  // ---------------------------------------------------------------- modal ---
  function modal(title, bodyNode, onSave, saveLabel = "Save") {
    const back = el(`<div class="modal-backdrop"></div>`);
    const box = el(`<div class="modal"><h3>${esc(title)}</h3><div class="body"></div>
      <div class="foot"><button class="btn ghost" data-cancel>Cancel</button>
      <button class="btn" data-save>${esc(saveLabel)}</button></div></div>`);
    $(".body", box).appendChild(bodyNode);
    back.appendChild(box);
    document.body.appendChild(back);
    const close = () => back.remove();
    $("[data-cancel]", box).onclick = close;
    back.onclick = (e) => { if (e.target === back) close(); };
    $("[data-save]", box).onclick = async () => {
      try { await onSave(close); } catch (err) { toast(err.message, true); }
    };
    return { close, box };
  }

  function field(label, name, opts = {}) {
    const { type = "text", value = "", options } = opts;
    if (options) {
      const sel = el(`<select name="${name}"></select>`);
      options.forEach((o) => sel.appendChild(el(`<option value="${esc(o.value)}" ${o.value == value ? "selected" : ""}>${esc(o.label)}</option>`)));
      const wrap = el(`<div><label>${esc(label)}</label></div>`); wrap.appendChild(sel); return wrap;
    }
    const wrap = el(`<div><label>${esc(label)}</label><input name="${name}" type="${type}" value="${esc(value)}" /></div>`);
    return wrap;
  }
  const formValues = (node) => {
    const out = {};
    node.querySelectorAll("input,select,textarea").forEach((i) => { if (i.name) out[i.name] = i.value; });
    return out;
  };

  // ------------------------------------------------------------- login UI ---
  function renderLogin() {
    const root = $("#root");
    root.innerHTML = "";
    const card = el(`<div class="login-wrap"><div class="login-card">
      <h1>Acme ERP</h1><p class="sub">Sign in to your workspace</p>
      <label>Email</label><input id="email" value="admin@acme.test" />
      <label>Password</label><input id="pw" type="password" value="admin123" />
      <div style="margin-top:1.25rem"><button class="btn" id="go" style="width:100%">Sign in</button></div>
      <div class="hint"><b>Demo logins</b><br/>admin@acme.test / admin123 (admin)<br/>manager@acme.test / manager123</div>
    </div></div>`);
    root.appendChild(card);
    const submit = async () => {
      try {
        const data = await api("/auth/login", { form: { username: $("#email").value, password: $("#pw").value } });
        State.token = data.access_token; State.user = data.user;
        localStorage.setItem("erp_token", State.token);
        localStorage.setItem("erp_user", JSON.stringify(State.user));
        location.hash = "#/dashboard"; render();
      } catch (e) { toast(e.message, true); }
    };
    $("#go", card).onclick = submit;
    $("#pw", card).addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  }

  // -------------------------------------------------------------- shell ------
  const NAV = [
    { group: "Overview" },
    { id: "dashboard", label: "Dashboard" },
    { group: "Operations" },
    { id: "products", label: "Products" },
    { id: "inventory", label: "Inventory" },
    { group: "Sales" },
    { id: "customers", label: "Customers" },
    { id: "sales", label: "Sales Orders" },
    { id: "crm", label: "CRM / Leads" },
    { group: "Procurement" },
    { id: "suppliers", label: "Suppliers" },
    { id: "purchasing", label: "Purchase Orders" },
    { group: "Finance & People" },
    { id: "accounting", label: "Accounting" },
    { id: "hr", label: "Employees" },
  ];

  function renderShell(active) {
    const root = $("#root");
    root.innerHTML = "";
    const navHtml = NAV.map((n) => n.group
      ? `<div class="group">${n.label || n.group}</div>`
      : `<a href="#/${n.id}" class="${n.id === active ? "active" : ""}">${esc(n.label)}</a>`).join("");
    const shell = el(`<div class="app">
      <aside class="sidebar">
        <div class="brand">Acme ERP <small>Enterprise Resource Planning</small></div>
        <nav class="nav">${navHtml}</nav>
      </aside>
      <div class="main">
        <div class="topbar"><h2 id="page-title"></h2>
          <div class="userbox"><span>${esc(State.user?.full_name || "")} · <b>${esc(State.user?.role || "")}</b></span>
          <button class="btn ghost sm" id="logout">Sign out</button></div>
        </div>
        <div class="content" id="content"></div>
      </div></div>`);
    root.appendChild(shell);
    $("#logout", shell).onclick = logout;
    return { title: $("#page-title", shell), content: $("#content", shell) };
  }

  // -------------------------------------------------------- generic table ----
  function tableCard(title, columns, rows, opts = {}) {
    const card = el(`<div class="card"></div>`);
    const head = el(`<div class="card-head"><h3>${esc(title)}</h3></div>`);
    if (opts.action) head.appendChild(opts.action);
    card.appendChild(head);
    if (!rows.length) { card.appendChild(el(`<div class="empty">Nothing here yet.</div>`)); return card; }
    const thead = columns.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("");
    const tbody = rows.map((r) => "<tr>" + columns.map((c) => {
      const v = c.render ? c.render(r) : esc(r[c.key]);
      return `<td class="${c.num ? "num" : ""}">${v}</td>`;
    }).join("") + "</tr>").join("");
    card.appendChild(el(`<table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`));
    return card;
  }
  const badge = (s) => `<span class="badge ${esc(s)}">${esc(s)}</span>`;

  // =====================================================================
  // VIEWS
  // =====================================================================
  const Views = {};

  Views.dashboard = async (c) => {
    const d = await api("/dashboard");
    const kpis = [
      ["Revenue (posted)", money(d.revenue), "good"],
      ["Purchases (payable)", money(d.purchases), ""],
      ["Inventory value", money(d.inventory_value), "accent"],
      ["Open pipeline", money(d.pipeline_value), "accent"],
      ["Products", d.products, ""],
      ["Low stock", d.low_stock, d.low_stock ? "warn" : "good"],
      ["Customers", d.customers, ""],
      ["Suppliers", d.suppliers, ""],
      ["Open sales orders", d.open_sales_orders, ""],
      ["Open purchase orders", d.open_purchase_orders, ""],
      ["Employees", d.employees, ""],
      ["Open leads", d.open_leads, ""],
    ];
    const grid = el(`<div class="kpis"></div>`);
    kpis.forEach(([label, value, cls]) => grid.appendChild(
      el(`<div class="kpi ${cls}"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`)));
    c.appendChild(grid);
    c.appendChild(el(`<div class="card"><div class="body muted">
      This demo company is pre-seeded with products, a confirmed sales order and a received purchase order,
      so the accounting figures above are produced by real double-entry postings — not hard-coded numbers.
      Explore the modules from the sidebar; every action (confirming an order, receiving stock, adjusting inventory)
      updates the ledger and these KPIs.</div></div>`));
  };

  // ---- Products ----
  Views.products = async (c) => {
    const rows = await api("/products");
    const add = el(`<button class="btn sm">+ New product</button>`);
    add.onclick = () => productModal();
    c.appendChild(tableCard("Products", [
      { key: "sku", label: "SKU" },
      { key: "name", label: "Name" },
      { key: "category", label: "Category" },
      { key: "unit_price", label: "Sell", num: true, render: (r) => money(r.unit_price) },
      { key: "cost_price", label: "Cost", num: true, render: (r) => money(r.cost_price) },
      { key: "on_hand", label: "On hand", num: true },
      { key: "reorder_level", label: "Reorder", num: true },
      { key: "stock", label: "Status", render: (r) => r.on_hand <= r.reorder_level ? badge("low") : badge("ok") },
    ], rows, { action: add }));
  };
  function productModal() {
    const body = el(`<div></div>`);
    body.append(
      field("SKU", "sku"), field("Name", "name"), field("Category", "category"),
      el(`<div class="row"></div>`));
    const row = $(".row", body);
    row.append(field("Sell price", "unit_price", { type: "number" }), field("Cost price", "cost_price", { type: "number" }));
    body.append(field("Reorder level", "reorder_level", { type: "number", value: 0 }));
    modal("New product", body, async (close) => {
      const v = formValues(body);
      await api("/products", { method: "POST", body: {
        sku: v.sku, name: v.name, category: v.category || "General",
        unit_price: v.unit_price || 0, cost_price: v.cost_price || 0, reorder_level: parseInt(v.reorder_level || 0),
      }});
      toast("Product created"); close(); route();
    });
  }

  // ---- Inventory ----
  Views.inventory = async (c) => {
    const [stock, products, warehouses] = await Promise.all([api("/stock"), api("/products"), api("/warehouses")]);
    State.cache.products = products; State.cache.warehouses = warehouses;
    const add = el(`<button class="btn sm">+ Adjust stock</button>`);
    add.onclick = () => adjustModal(products, warehouses);
    c.appendChild(tableCard("Stock on hand", [
      { key: "product_name", label: "Product" },
      { key: "warehouse_name", label: "Warehouse" },
      { key: "quantity", label: "Quantity", num: true },
    ], stock, { action: add }));

    const whCard = el(`<div class="card"><div class="card-head"><h3>Warehouses</h3></div></div>`);
    const addWh = el(`<button class="btn sm">+ Warehouse</button>`);
    addWh.onclick = () => warehouseModal();
    $(".card-head", whCard).appendChild(addWh);
    whCard.appendChild(el(`<table><thead><tr><th>Code</th><th>Name</th><th>Location</th></tr></thead>
      <tbody>${warehouses.map((w) => `<tr><td>${esc(w.code)}</td><td>${esc(w.name)}</td><td>${esc(w.location)}</td></tr>`).join("")}</tbody></table>`));
    c.appendChild(whCard);
  };
  function adjustModal(products, warehouses) {
    const body = el(`<div></div>`);
    body.append(
      field("Product", "product_id", { options: products.map((p) => ({ value: p.id, label: `${p.sku} — ${p.name}` })) }),
      field("Warehouse", "warehouse_id", { options: warehouses.map((w) => ({ value: w.id, label: w.name })) }),
      field("Quantity change (+/-)", "quantity", { type: "number", value: 0 }),
      field("Reference", "reference", { value: "manual adjustment" }));
    modal("Adjust stock", body, async (close) => {
      const v = formValues(body);
      await api("/stock/adjust", { method: "POST", body: {
        product_id: +v.product_id, warehouse_id: +v.warehouse_id, quantity: parseInt(v.quantity), reference: v.reference }});
      toast("Stock adjusted"); close(); route();
    });
  }
  function warehouseModal() {
    const body = el(`<div></div>`);
    body.append(field("Code", "code"), field("Name", "name"), field("Location", "location"));
    modal("New warehouse", body, async (close) => {
      const v = formValues(body);
      await api("/warehouses", { method: "POST", body: v });
      toast("Warehouse created"); close(); route();
    });
  }

  // ---- Customers ----
  Views.customers = async (c) => {
    const rows = await api("/customers");
    const add = el(`<button class="btn sm">+ New customer</button>`);
    add.onclick = () => contactModal("customer");
    c.appendChild(tableCard("Customers", [
      { key: "name", label: "Name" }, { key: "email", label: "Email" }, { key: "phone", label: "Phone" },
    ], rows, { action: add }));
  };
  // ---- Suppliers ----
  Views.suppliers = async (c) => {
    const rows = await api("/suppliers");
    const add = el(`<button class="btn sm">+ New supplier</button>`);
    add.onclick = () => contactModal("supplier");
    c.appendChild(tableCard("Suppliers", [
      { key: "name", label: "Name" }, { key: "email", label: "Email" }, { key: "phone", label: "Phone" },
    ], rows, { action: add }));
  };
  function contactModal(kind) {
    const body = el(`<div></div>`);
    body.append(field("Name", "name"), field("Email", "email"), field("Phone", "phone"),
      field(kind === "customer" ? "Billing address" : "Address", "address"));
    modal(`New ${kind}`, body, async (close) => {
      const v = formValues(body);
      const payload = { name: v.name, email: v.email, phone: v.phone };
      if (kind === "customer") { payload.billing_address = v.address; await api("/customers", { method: "POST", body: payload }); }
      else { payload.address = v.address; await api("/suppliers", { method: "POST", body: payload }); }
      toast(`${kind[0].toUpperCase() + kind.slice(1)} created`); close(); route();
    });
  }

  // ---- Order view builder (shared by sales & purchasing) ----
  function orderView(kind) {
    // kind: { title, list, create, partyLabel, partyList, priceKey, actions }
    return async (c) => {
      const [orders, parties, products, warehouses] = await Promise.all([
        api(kind.listPath), api(kind.partyPath), api("/products"), api("/warehouses")]);
      const add = el(`<button class="btn sm">+ New ${kind.noun}</button>`);
      add.onclick = () => orderModal(kind, parties, products, warehouses);
      const cols = [
        { key: "number", label: "Number" },
        { key: "party", label: kind.partyLabel, render: (r) => esc(r[kind.partyNameKey]) },
        { key: "order_date", label: "Date" },
        { key: "total", label: "Total", num: true, render: (r) => money(r.total) },
        { key: "status", label: "Status", render: (r) => badge(r.status) },
        { key: "act", label: "", render: (r) => r.status === "draft"
          ? `<div class="actions"><button class="btn sm success" data-do="${kind.confirmVerb}" data-id="${r.id}">${kind.confirmLabel}</button>
             <button class="btn sm ghost" data-do="cancel" data-id="${r.id}">Cancel</button></div>` : `<span class="muted">—</span>` },
      ];
      const card = tableCard(kind.title, cols, orders, { action: add });
      card.querySelectorAll("[data-do]").forEach((b) => b.onclick = async () => {
        try {
          await api(`${kind.basePath}/${b.dataset.id}/${b.dataset.do}`, { method: "POST" });
          toast("Done"); route();
        } catch (e) { toast(e.message, true); }
      });
      c.appendChild(card);
      // pipeline of line items shown when expanding — kept simple: show under table
    };
  }
  function orderModal(kind, parties, products, warehouses) {
    const body = el(`<div></div>`);
    body.append(
      field(kind.partyLabel, "party_id", { options: parties.map((p) => ({ value: p.id, label: p.name })) }),
      field("Warehouse", "warehouse_id", { options: warehouses.map((w) => ({ value: w.id, label: w.name })) }));
    const linesWrap = el(`<div><label>Line items</label></div>`);
    body.appendChild(linesWrap);
    const addLine = () => {
      const lr = el(`<div class="line-row"></div>`);
      const prod = el(`<select></select>`);
      products.forEach((p) => prod.appendChild(el(`<option value="${p.id}" data-price="${kind.priceKey === "unit_price" ? p.unit_price : p.cost_price}">${esc(p.sku)} — ${esc(p.name)}</option>`)));
      const qty = el(`<input type="number" value="1" min="1" placeholder="Qty" />`);
      const price = el(`<input type="number" step="0.01" placeholder="Price" />`);
      const setP = () => { price.value = prod.selectedOptions[0].dataset.price; };
      prod.onchange = setP; setP();
      const del = el(`<button class="btn sm ghost">✕</button>`); del.onclick = () => lr.remove();
      lr.append(prod, qty, price, del);
      lr._get = () => ({ product_id: +prod.value, quantity: parseInt(qty.value), unit_price: parseFloat(price.value) });
      linesWrap.appendChild(lr);
    };
    const addBtn = el(`<button class="btn ghost sm" style="margin-top:.25rem">+ Add line</button>`);
    addBtn.onclick = addLine; linesWrap.appendChild(addBtn);
    addLine();
    modal(`New ${kind.noun}`, body, async (close) => {
      const v = formValues(body);
      const lines = Array.from(linesWrap.querySelectorAll(".line-row")).map((r) => r._get());
      await api(kind.listPath, { method: "POST", body: {
        [kind.partyField]: +v.party_id, warehouse_id: +v.warehouse_id, lines }});
      toast(`${kind.noun} created`); close(); route();
    }, "Create");
  }

  Views.sales = orderView({
    title: "Sales Orders", noun: "sales order", basePath: "/sales-orders", listPath: "/sales-orders",
    partyPath: "/customers", partyLabel: "Customer", partyField: "customer_id", partyNameKey: "customer_name",
    priceKey: "unit_price", confirmVerb: "confirm", confirmLabel: "Confirm",
  });
  Views.purchasing = orderView({
    title: "Purchase Orders", noun: "purchase order", basePath: "/purchase-orders", listPath: "/purchase-orders",
    partyPath: "/suppliers", partyLabel: "Supplier", partyField: "supplier_id", partyNameKey: "supplier_name",
    priceKey: "cost_price", confirmVerb: "receive", confirmLabel: "Receive",
  });

  // ---- Accounting ----
  Views.accounting = async (c) => {
    const [accounts, journal, tb] = await Promise.all([api("/accounts"), api("/journal"), api("/trial-balance")]);
    const addAcc = el(`<button class="btn sm">+ Account</button>`);
    addAcc.onclick = () => accountModal();
    c.appendChild(tableCard("Chart of Accounts", [
      { key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "type", label: "Type" },
      { key: "balance", label: "Balance", num: true, render: (r) => money(r.balance) },
    ], accounts, { action: addAcc }));

    const tbCard = el(`<div class="card"><div class="card-head"><h3>Trial Balance</h3>
      <span class="badge ${tb.balanced ? "ok" : "low"}">${tb.balanced ? "Balanced" : "Out of balance"}</span></div></div>`);
    tbCard.appendChild(el(`<table><thead><tr><th>Code</th><th>Account</th><th class="num">Debit</th><th class="num">Credit</th></tr></thead>
      <tbody>${tb.rows.map((r) => `<tr><td>${esc(r.code)}</td><td>${esc(r.name)}</td>
        <td class="num">${r.debit ? money(r.debit) : ""}</td><td class="num">${r.credit ? money(r.credit) : ""}</td></tr>`).join("")}
      <tr style="font-weight:700"><td></td><td>Total</td><td class="num">${money(tb.total_debit)}</td><td class="num">${money(tb.total_credit)}</td></tr>
      </tbody></table>`));
    c.appendChild(tbCard);

    const addJ = el(`<button class="btn sm">+ Journal entry</button>`);
    addJ.onclick = () => journalModal(accounts);
    const jCard = el(`<div class="card"><div class="card-head"><h3>Journal</h3></div></div>`);
    $(".card-head", jCard).appendChild(addJ);
    if (!journal.length) jCard.appendChild(el(`<div class="empty">No entries.</div>`));
    else journal.forEach((e) => {
      const t = el(`<div style="border-bottom:1px solid var(--border);padding:.6rem 1.25rem">
        <div style="font-size:.85rem"><b>#${e.id}</b> · ${esc(e.entry_date)} · ${esc(e.memo)} <span class="badge ${e.source === "manual" ? "new" : "qualified"}">${esc(e.source)}</span></div>
        <table style="margin-top:.35rem">${e.lines.map((l) => `<tr><td>${esc(l.account_name)}</td>
          <td class="num">${Number(l.debit) ? money(l.debit) : ""}</td><td class="num">${Number(l.credit) ? money(l.credit) : ""}</td></tr>`).join("")}</table></div>`);
      jCard.appendChild(t);
    });
    c.appendChild(jCard);
  };
  function accountModal() {
    const body = el(`<div></div>`);
    body.append(field("Code", "code"), field("Name", "name"),
      field("Type", "type", { options: ["asset", "liability", "equity", "income", "expense"].map((t) => ({ value: t, label: t })) }));
    modal("New account", body, async (close) => {
      await api("/accounts", { method: "POST", body: formValues(body) });
      toast("Account created"); close(); route();
    });
  }
  function journalModal(accounts) {
    const body = el(`<div></div>`);
    body.append(field("Memo", "memo"));
    const wrap = el(`<div><label>Lines (debits must equal credits)</label></div>`);
    body.appendChild(wrap);
    const addLine = () => {
      const lr = el(`<div class="line-row"></div>`);
      const acc = el(`<select></select>`);
      accounts.forEach((a) => acc.appendChild(el(`<option value="${a.id}">${esc(a.code)} ${esc(a.name)}</option>`)));
      const dr = el(`<input type="number" step="0.01" placeholder="Debit" value="0" />`);
      const cr = el(`<input type="number" step="0.01" placeholder="Credit" value="0" />`);
      const del = el(`<button class="btn sm ghost">✕</button>`); del.onclick = () => lr.remove();
      lr.append(acc, dr, cr, del);
      lr._get = () => ({ account_id: +acc.value, debit: parseFloat(dr.value || 0), credit: parseFloat(cr.value || 0) });
      wrap.appendChild(lr);
    };
    const addBtn = el(`<button class="btn ghost sm" style="margin-top:.25rem">+ Add line</button>`);
    addBtn.onclick = addLine; wrap.appendChild(addBtn);
    addLine(); addLine();
    modal("New journal entry", body, async (close) => {
      const v = formValues(body);
      const lines = Array.from(wrap.querySelectorAll(".line-row")).map((r) => r._get());
      await api("/journal", { method: "POST", body: { memo: v.memo, lines } });
      toast("Entry posted"); close(); route();
    }, "Post");
  }

  // ---- HR ----
  Views.hr = async (c) => {
    const [emps, depts] = await Promise.all([api("/employees"), api("/departments")]);
    State.cache.depts = depts;
    const add = el(`<button class="btn sm">+ New employee</button>`);
    add.onclick = () => employeeModal(depts);
    c.appendChild(tableCard("Employees", [
      { key: "full_name", label: "Name" }, { key: "position", label: "Position" },
      { key: "department_name", label: "Department" },
      { key: "salary", label: "Salary", num: true, render: (r) => money(r.salary) },
      { key: "hire_date", label: "Hired" },
      { key: "is_active", label: "Status", render: (r) => r.is_active ? badge("ok") : badge("cancelled") },
    ], emps, { action: add }));
  };
  function employeeModal(depts) {
    const body = el(`<div></div>`);
    body.append(field("Full name", "full_name"), field("Email", "email"), field("Position", "position"),
      field("Department", "department_id", { options: depts.map((d) => ({ value: d.id, label: d.name })) }),
      field("Salary", "salary", { type: "number" }));
    modal("New employee", body, async (close) => {
      const v = formValues(body);
      await api("/employees", { method: "POST", body: {
        full_name: v.full_name, email: v.email, position: v.position,
        department_id: v.department_id ? +v.department_id : null, salary: v.salary || 0 }});
      toast("Employee added"); close(); route();
    });
  }

  // ---- CRM ----
  Views.crm = async (c) => {
    const leads = await api("/leads");
    const stages = ["new", "qualified", "proposal", "won", "lost"];
    const add = el(`<button class="btn sm">+ New lead</button>`);
    add.onclick = () => leadModal(stages);
    // pipeline summary
    const byStage = {}; stages.forEach((s) => byStage[s] = { count: 0, value: 0 });
    leads.forEach((l) => { byStage[l.stage].count++; byStage[l.stage].value += Number(l.estimated_value); });
    const grid = el(`<div class="kpis"></div>`);
    stages.forEach((s) => grid.appendChild(el(`<div class="kpi"><div class="label">${s}</div>
      <div class="value" style="font-size:1.3rem">${byStage[s].count}</div><div class="muted">${money(byStage[s].value)}</div></div>`)));
    c.appendChild(grid);
    const card = tableCard("Leads", [
      { key: "name", label: "Opportunity" }, { key: "company", label: "Company" },
      { key: "owner", label: "Owner" },
      { key: "estimated_value", label: "Value", num: true, render: (r) => money(r.estimated_value) },
      { key: "stage", label: "Stage", render: (r) => badge(r.stage) },
      { key: "act", label: "", render: (r) => `<button class="btn sm ghost" data-id="${r.id}">Move</button>` },
    ], leads, { action: add });
    card.querySelectorAll("[data-id]").forEach((b) => b.onclick = () => {
      const lead = leads.find((l) => l.id == b.dataset.id);
      leadModal(stages, lead);
    });
    c.appendChild(card);
  };
  function leadModal(stages, lead) {
    const body = el(`<div></div>`);
    body.append(
      field("Opportunity", "name", { value: lead?.name || "" }),
      field("Company", "company", { value: lead?.company || "" }),
      field("Contact email", "contact_email", { value: lead?.contact_email || "" }),
      field("Owner", "owner", { value: lead?.owner || "" }),
      field("Estimated value", "estimated_value", { type: "number", value: lead?.estimated_value || 0 }),
      field("Stage", "stage", { value: lead?.stage || "new", options: stages.map((s) => ({ value: s, label: s })) }));
    modal(lead ? "Update lead" : "New lead", body, async (close) => {
      const v = formValues(body);
      const payload = { name: v.name, company: v.company, contact_email: v.contact_email,
        owner: v.owner, estimated_value: v.estimated_value || 0, stage: v.stage };
      if (lead) await api(`/leads/${lead.id}`, { method: "PUT", body: payload });
      else await api("/leads", { method: "POST", body: payload });
      toast("Saved"); close(); route();
    });
  }

  // =====================================================================
  // Router
  // =====================================================================
  let currentShell = null;
  async function route() {
    if (!State.token) { renderLogin(); return; }
    const id = (location.hash.replace("#/", "") || "dashboard");
    const view = Views[id] || Views.dashboard;
    currentShell = renderShell(id);
    currentShell.title.textContent = (NAV.find((n) => n.id === id) || {}).label || "Dashboard";
    currentShell.content.innerHTML = `<div class="empty">Loading…</div>`;
    try {
      currentShell.content.innerHTML = "";
      await view(currentShell.content);
    } catch (e) {
      currentShell.content.innerHTML = "";
      currentShell.content.appendChild(el(`<div class="card"><div class="empty">${esc(e.message)}</div></div>`));
    }
  }

  function render() { route(); }
  window.addEventListener("hashchange", route);
  render();
})();
