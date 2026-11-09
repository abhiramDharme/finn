const WAKE_ALL = [
  ["results", "Results"],
  ["m_and_a", "M&A"],
  ["fund_raise", "Fund raise"],
  ["management_change", "Management"],
  ["litigation", "Litigation"],
  ["insider_trading", "Insider buying or selling"],
  ["credit_rating", "Credit rating"],
  ["capex", "Capex"],
  ["pledging", "Pledging"],
  ["dividend", "Dividend"],
  ["earnings_call", "Earnings call"],
  ["press_release", "Other updates"],
];
const DEFAULT_WAKE = ["results", "m_and_a", "fund_raise", "management_change", "litigation", "insider_trading", "credit_rating", "capex", "pledging"];

const state = {
  view: "brief",
  window: localStorage.getItem("finn.window") || "24h",
  price: Number(localStorage.getItem("finn.price") || 3),
  volume: Number(localStorage.getItem("finn.volume") || 2),
  wake: JSON.parse(localStorage.getItem("finn.wake") || "null") || DEFAULT_WAKE,
  brief: null,
  memo: null,
  person: null,
  network: null,
  query: "",
  settings: false,
  open: {},
  away: false,
  loading: "Reading the book",
  error: null,
  ask: null,
  asking: false,
};

const app = document.getElementById("app");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function indian(value) {
  if (value == null || Number.isNaN(Number(value))) return "";
  const neg = value < 0;
  const [whole, frac] = Math.abs(Number(value)).toFixed(2).split(".");
  let body;
  if (whole.length <= 3) body = whole;
  else {
    const tail = whole.slice(-3);
    let head = whole.slice(0, -3);
    const parts = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) parts.unshift(head);
    body = parts.join(",") + "," + tail;
  }
  const showFrac = frac === "00" ? "" : "." + frac.replace(/0$/, "");
  return (neg ? "-" : "") + body + showFrac;
}
function save() {
  localStorage.setItem("finn.window", state.window);
  localStorage.setItem("finn.price", String(state.price));
  localStorage.setItem("finn.volume", String(state.volume));
  localStorage.setItem("finn.wake", JSON.stringify(state.wake));
}
async function getJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (err) { /* keep status */ }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return response.json();
}

async function loadBrief() {
  state.loading = state.brief ? null : "Reading the book";
  state.error = null;
  render();
  try {
    const wake = state.wake.join(",");
    state.brief = await getJSON(`/api/brief?window=${state.window}&price=${state.price}&volume=${state.volume}&wake=${encodeURIComponent(wake)}`);
    state.loading = null;
    const first = (state.brief.now || [])[0];
    if (first && state.open[first.id] == null) state.open[first.id] = true;
  } catch (err) {
    state.error = err.message;
    state.loading = null;
  }
  render();
}

async function loadMemo(symbol, live) {
  state.view = "company";
  state.settings = false;
  state.memo = null;
  state.ask = null;
  state.loading = live ? `Reading filings for ${symbol}. The first time takes a minute.` : `Opening ${symbol}`;
  state.error = null;
  render();
  try {
    if (live) state.memo = await getJSON(`/api/live/${symbol}`, { method: "POST" });
    else {
      try { state.memo = await getJSON(`/api/company/${symbol}`); }
      catch (err) {
        if (/No statements/.test(err.message)) {
          state.loading = null;
          state.error = null;
          state.memo = { missing: symbol };
          render();
          return;
        }
        throw err;
      }
    }
    state.loading = null;
  } catch (err) {
    state.error = err.message;
    state.loading = null;
  }
  render();
}

async function loadNetwork(query) {
  state.network = await getJSON(`/api/network?q=${encodeURIComponent(query || "")}`);
}

async function loadPerson(id) {
  state.view = "people";
  state.person = null;
  state.loading = "Opening the notebook";
  render();
  try {
    state.person = await getJSON(`/api/person/${id}`);
    state.loading = null;
  } catch (err) {
    state.error = err.message;
    state.loading = null;
  }
  render();
}

function known() {
  const brief = state.brief || {};
  return [...(brief.portfolio || []), ...(brief.research || [])];
}

function route(raw) {
  const text = raw.trim();
  if (!text) return;
  const lower = text.toLowerCase();
  if (/^(today|brief|what changed|what's important|whats important)$/.test(lower)) {
    state.view = "brief";
    state.settings = false;
    render();
    return;
  }
  if (/^who\b|who should i call|who knows/.test(lower)) {
    state.view = "people";
    state.person = null;
    state.query = text.replace(/^who (knows|should i call about|can tell me about)?\s*/i, "");
    openPeople();
    return;
  }
  const hit = known().find((company) => company.symbol.toLowerCase() === lower || company.name.toLowerCase() === lower);
  if (hit) { loadMemo(hit.symbol); return; }
  if (/^[a-z][a-z0-9&-]{1,15}$/i.test(text) && !/^(the|and|for|how|why|what)$/i.test(text)) {
    loadMemo(text.toUpperCase());
    return;
  }
  if (state.memo && state.view === "company") { ask(text); return; }
  state.view = "people";
  state.query = text;
  openPeople();
}

async function openPeople() {
  state.person = null;
  state.settings = false;
  state.loading = state.network ? null : "Opening the notebook";
  render();
  try { await loadNetwork(state.query); state.loading = null; }
  catch (err) { state.error = err.message; state.loading = null; }
  render();
}

async function ask(question) {
  if (!state.memo) return;
  state.asking = true;
  state.ask = null;
  render();
  try { state.ask = await getJSON("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: state.memo.symbol, question }) }); }
  catch (err) { state.ask = { refused: true, answer: err.message, quotes: [] }; }
  state.asking = false;
  render();
}

function render() {
  const pages = { brief: renderBrief, company: renderCompany, people: renderPeople };
  const body = state.settings ? renderSettings() : (pages[state.view] || renderBrief)();
  app.innerHTML = body + renderNav();
}

function renderNav() {
  const item = (view, label) => `<button data-act="view" data-view="${view}" class="${state.view === view && !state.settings ? "on" : ""}">${label}</button>`;
  return `<nav class="nav">${item("brief", "Brief")}${item("company", "Company")}${item("people", "People")}</nav>`;
}

function renderBrief() {
  if (state.loading && !state.brief) return `<div class="page"><p class="status">${esc(state.loading)}</p></div>`;
  if (state.error && !state.brief) return `<div class="page"><p class="status">${esc(state.error)}</p></div>`;
  const brief = state.brief;
  if (!brief) return `<div class="page"><p class="status">Nothing loaded.</p></div>`;
  const when = new Date(brief.as_of);
  const date = when.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const windows = ["24h", "3d", "7d", "30d"].map((key) => `<button data-act="window" data-window="${key}" class="${brief.window.key === key ? "on" : ""}">${key === "24h" ? "24 hours" : key}</button>`).join("");
  const alerts = (brief.alerts || []).map((alert) => {
    const cls = alert.pct < 0 ? "down" : "up";
    const bits = [];
    if (alert.price_hit) bits.push(alert.pct_label);
    if (alert.volume_hit && alert.vol_x) bits.push(`${alert.vol_x.toFixed(1)}× volume`);
    const filing = alert.has_filing ? "Filing the same day" : "No filing that day";
    return `<button class="alert" data-act="company" data-symbol="${esc(alert.symbol)}"><span><b>${esc(alert.name)}</b><span class="quiet"> · ${filing}</span></span><span class="num ${cls}">${esc(bits.join(" · "))}</span></button>`;
  }).join("");
  const aside = brief.aside ? `<button class="aside" data-act="window" data-window="7d">${brief.aside.count} thing${brief.aside.count === 1 ? "" : "s"} in the last 7 days sat outside this window. ${esc(brief.aside.name)}: ${esc(brief.aside.line)}</button>` : "";
  const now = (brief.now || []).map((card) => renderCard(card, true)).join("");
  const glance = (brief.glance || []).map((card) => renderCard(card, false)).join("");
  const awayItems = state.away ? (brief.away.items || []).map((card) => `<div class="item thin"><div class="sym">${esc(card.name)} · ${esc(card.category_label)}<span class="when">${esc(card.when)}</span></div><h3>${esc(card.line)}</h3></div>`).join("") : "";
  const reconnect = (brief.reconnect || []).filter((item) => !(brief.now || []).some((card) => card.contact && card.contact.id === item.id)).slice(0, 2);
  const calls = reconnect.map((item) => `<button class="item item-top" data-act="person" data-id="${esc(item.id)}"><div class="sym">Call · ${esc(item.company)}</div><h3>${esc(item.opener)}</h3><p class="note">${esc(item.why)}</p></button>`).join("");
  const book = brief.book ? `<p class="quiet bookline">${brief.book.skipped_short_session ? `${esc(formatDate(brief.book.skipped_short_session))} was a thin session, so the line is the previous full close. ` : ""}${esc(formatDate(brief.book.date))} · ${brief.book.up} up, ${brief.book.down} down, of ${brief.book.names}.</p>` : "";
  return `<div class="page">
    <header class="mast"><div class="mark">FINN</div><button class="mast-meta" data-act="settings">${esc(date)} · watch</button></header>
    <p class="who">${esc(brief.investor)} · private desk</p>
    <form class="command" data-act="command"><input name="q" placeholder="A company, a person, or what changed" autocomplete="off" enterkeyhint="search"></form>
    <div class="windows">${windows}</div>
    <p class="lede">${esc(brief.lede)}</p>
    ${aside}
    ${book}
    <p class="kicker">Last close · outside ±${brief.thresholds.price_pct}% or ${brief.thresholds.volume_x}× volume</p>
    ${alerts || `<p class="quiet">Nothing in the book broke the line.</p>`}
    ${now ? `<p class="kicker">Needs you</p>${now}` : ""}
    ${calls ? `<p class="kicker">Worth a call</p>${calls}` : ""}
    ${glance ? `<p class="kicker">A glance</p>${glance}` : ""}
    <button class="fold" data-act="away">${state.away ? "Hide" : "Filed away"} · ${brief.away.count} routine</button>
    ${awayItems}
    <p class="fineprint">Filings from NSE. Prices from the exchange bhavcopy. The notebook is synthetic. Numbers are not from news or broker notes.</p>
  </div>`;
}

function renderCard(card, primary) {
  const open = state.open[card.id];
  const head = `<button class="item-top" data-act="toggle" data-id="${esc(card.id)}">
      <div class="sym">${esc(card.name)} · ${esc(card.category_label)}<span class="when">${esc(card.when)}</span></div>
      <h3>${esc(card.line)}</h3>
    </button>`;
  if (!open) return `<article class="item ${primary ? "" : "glance"}">${head}</article>`;
  const nums = card.numbers ? `<table class="nums"><thead><tr><th>${esc(card.numbers.period)}</th><th></th><th>QoQ</th><th>YoY</th></tr></thead><tbody>${
    card.numbers.rows.map((row) => `<tr><td>${esc(row.label)}</td><td class="num">${esc(row.value)}</td><td class="num ${signed(row.qoq)}">${esc(row.qoq || "—")}</td><td class="num ${signed(row.yoy)}">${esc(row.yoy || "—")}</td></tr>`).join("")
  }</tbody></table><p class="note">${esc(card.numbers.note)} ${esc(card.numbers.unit)}.</p>` : "";
  const person = card.person && (card.person.bio || card.person.note) ? `<p class="bio">${esc(card.person.bio || card.person.note)}</p><p class="source">From the filing${card.person.previous_org ? ` · previously ${esc(card.person.previous_org)}` : ""}</p>` : "";
  const contact = card.contact ? `<div class="who-block"><div class="strength">${esc(strengthLabel(card.contact.strength))}</div><strong>${esc(card.contact.name)}</strong><p>${esc(card.contact.reasons.join(" "))}</p><p class="note">${card.contact.stale ? "You last spoke" : "Last spoke"} ${esc(prettyDate(card.contact.last_touch))}.</p></div>` : "";
  return `<article class="item">${head}${nums}${person}${contact}<p class="links">${card.url ? `<a href="${esc(card.url)}" target="_blank" rel="noopener">Open the filing</a>` : ""}<button data-act="company" data-symbol="${esc(card.symbol)}">Open ${esc(card.name)}</button></p></article>`;
}

function strengthLabel(value) {
  return { "works there": "Works there", "was there": "Was there", "same institution": "Same institution", adjacent: "Adjacent", theme: "Knows the theme" }[value] || value;
}
function signed(value) { if (!value) return ""; return String(value).startsWith("−") || String(value).startsWith("-") ? "down" : "up"; }
function prettyDate(iso) {
  if (!iso) return "";
  const date = new Date(iso.slice(0, 10) + "T00:00:00");
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}
function formatDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  const date = new Date(Number(y), Number(m) - 1, Number(d));
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function renderCompany() {
  if (state.loading) return `<div class="page"><button class="back" data-act="view" data-view="brief">Back</button><p class="status">${esc(state.loading)}</p></div>`;
  if (state.memo && state.memo.missing) {
    return `<div class="page"><button class="back" data-act="view" data-view="company">Back</button><p class="lede">${esc(state.memo.missing)} isn't in the cached book.</p><p>The same engine can read it now, from the exchange filings and the annual documents.</p><button class="aside" data-act="live" data-symbol="${esc(state.memo.missing)}">Read ${esc(state.memo.missing)} from the filings</button>${renderPicker()}</div>`;
  }
  if (!state.memo) return `<div class="page"><header class="mast"><div class="mark">FINN</div></header><p class="who">Ask for any NSE symbol. The book is just where the demo starts.</p><form class="command" data-act="command"><input name="q" placeholder="RELIANCE, or a name outside the book" autocomplete="off"></form>${state.error ? `<p class="note">${esc(state.error)}</p>` : ""}${renderPicker()}</div>`;
  const memo = state.memo;
  const price = memo.price ? `<p class="price-line"><span class="num">₹${esc(indian(memo.price.close))}</span> <span class="${memo.price.pct < 0 ? "down" : "up"} num">${esc(signedPct(memo.price.pct))}</span><span class="muted">close ${esc(formatDate(memo.price.date))}</span></p>` : "";
  const market = Object.entries(memo.market || {}).map(([key, value]) => `<span class="tag">${esc(key)} ${esc(value)}</span>`).join("");
  return `<div class="page">
    <button class="back" data-act="clear-memo">All companies</button>
    <p class="kicker">${esc(memo.symbol)} · ${memo.in_portfolio ? "in the book" : "outside the book"}${memo.sector ? " · " + esc(memo.sector) : ""}</p>
    <h1 class="name">${esc(memo.name)}</h1>
    ${price}
    <div>${market}</div>
    ${sectionBusiness(memo)}
    ${sectionNumbers(memo)}
    ${sectionTrajectory(memo)}
    ${sectionBalance(memo)}
    ${sectionCash(memo)}
    ${sectionPromised(memo)}
    ${sectionGuidance(memo)}
    ${sectionCases(memo)}
    ${sectionContacts(memo)}
    ${sectionAsk(memo)}
    ${sectionSources(memo)}
  </div>`;
}

function renderPicker() {
  const brief = state.brief;
  if (!brief) return "";
  const list = (items, label) => `<p class="kicker">${label}</p>` + items.map((company) => `<button class="row" data-act="company" data-symbol="${esc(company.symbol)}"><span>${esc(company.name)}<span class="sub">${esc(company.sector)}</span></span><span class="quiet">${esc(company.symbol)}</span></button>`).join("");
  return list(brief.portfolio || [], "In the book") + list(brief.research || [], "For a question, outside the book");
}

function sectionBusiness(memo) {
  const text = memo.business && memo.business.text;
  const mixes = (memo.segments || []).map((seg) => seg.mix
    ? `<div class="mix"><span>${esc(seg.name)}</span><span class="num">${Math.round(seg.mix * 100)}%</span><i class="bar" style="width:${Math.max(4, Math.round(seg.mix * 100))}%"></i></div>`
    : `<span class="tag">${esc(seg.name)}</span>`).join("");
  const mixNote = mixes && !(memo.segments || []).some((seg) => seg.mix) ? `<p class="note">Segments the company reports. The rupee split isn't in the pages I can read, so it isn't invented.</p>` : "";
  if (!text && !mixes) return `<section class="section"><div class="idx">01</div><h2>What it is</h2><p class="note">The annual-report pages I could read didn't contain a clean description, so I won't invent one.</p></section>`;
  return `<section class="section"><div class="idx">01 · Business</div><h2>What it is</h2>${text ? `<blockquote>${esc(text)}</blockquote><p class="source">${esc(memo.business.source || "Annual report")}</p>` : ""}${mixNote}<div style="margin-top:12px">${mixes}</div></section>`;
}
function sectionNumbers(memo) {
  const snap = memo.snapshot;
  if (!snap) return `<section class="section"><div class="idx">02 · Financial snapshot</div><h2>The numbers</h2><p class="note">No quarterly statement was readable for this symbol.</p></section>`;
  const rows = snap.lines.map((line) => `<tr><td>${esc(line.label)}</td><td class="num">${esc(line.shown)}</td><td class="num ${signed(line.qoq)}">${esc(line.qoq || "—")}</td><td class="num ${signed(line.yoy)}">${esc(line.yoy || "—")}</td></tr>`).join("");
  return `<section class="section"><div class="idx">02 · Financial snapshot</div><h2>The numbers · ${esc(snap.period)}</h2><table class="nums"><thead><tr><th></th><th>₹ cr</th><th>QoQ</th><th>YoY</th></tr></thead><tbody>${rows}</tbody></table><p class="note">${esc(snap.note || "")} ${(snap.extra || []).map(esc).join(" · ")}</p></section>`;
}
function sectionTrajectory(memo) {
  const t = memo.trajectory || {};
  const row = (points) => `<div class="years">${(points || []).map((point) => `<div><span>${esc(point.label)}</span><b class="num">${esc(indian(point.value))}</b></div>`).join("")}</div>`;
  return `<section class="section"><div class="idx">03 · Trajectory</div><h2>The direction</h2><p>${esc(t.read || "")}</p><p class="source">${esc(t.sales_label || "Sales")}, ₹ cr</p>${row(t.sales)}</section>`;
}
function sectionBalance(memo) {
  const b = memo.balance || {};
  const bits = [];
  if (b.de != null) bits.push(`Debt / equity ${b.de.toFixed(2)}`);
  if (b.debtor_days != null) bits.push(`Debtors ${Math.round(b.debtor_days)}d`);
  if (b.inventory_days != null) bits.push(`Inventory ${Math.round(b.inventory_days)}d`);
  if (b.payable_days != null) bits.push(`Payables ${Math.round(b.payable_days)}d`);
  return `<section class="section"><div class="idx">04 · Balance sheet</div><h2>What it owes</h2><p>${esc(b.read || "")}</p><p class="note">${esc(bits.join(" · "))}</p></section>`;
}
function sectionCash(memo) {
  const c = memo.cash || {};
  const latest = (c.rows || []).slice(-4);
  const table = latest.length ? `<table class="nums"><thead><tr><th></th><th>CFO</th><th>PAT</th><th>FCF</th></tr></thead><tbody>${latest.map((row) => `<tr><td>${esc(row.label)}</td><td class="num">${esc(indian(row.cfo))}</td><td class="num">${row.pat == null ? "—" : esc(indian(row.pat))}</td><td class="num">${row.fcf == null ? "—" : esc(indian(row.fcf))}</td></tr>`).join("")}</tbody></table>` : "";
  return `<section class="section"><div class="idx">05 · Cash quality</div><h2>Does profit become cash</h2><p>${esc(c.read || "")}</p>${table}</section>`;
}
function sectionPromised(memo) {
  const blocks = (memo.promised || []).map((quarter) => `<div class="quarter"><h3>${esc(quarter.label)}</h3><p class="note num">Revenue ${esc(quarter.revenue || "—")} · ${esc(quarter.operating ? "OP " + quarter.operating : "")} · PBT ${esc(quarter.pbt || "—")} · PAT ${esc(quarter.pat || "—")} ${quarter.revenue_yoy ? "· rev " + esc(quarter.revenue_yoy) + " YoY" : ""}</p><p>${esc(quarter.read || "")}</p>${(quarter.quotes || []).map((quote) => `<p class="quote">“${esc(quote.text)}”</p><p class="source">${esc(quote.source)}</p>`).join("")}</div>`).join("");
  return `<section class="section"><div class="idx">06 · Narrative vs numbers</div><h2>Promised, then printed</h2><p class="note">Guidance is a sentence from the previous concall. The verdict is only shown when that sentence contained a number.</p>${blocks || "<p class='note'>No quarters to set a transcript against.</p>"}</section>`;
}
function sectionGuidance(memo) {
  const items = memo.guidance || [];
  if (!items.length) return `<section class="section"><div class="idx">07 · Guidance</div><h2>What they are saying now</h2><p class="note">I didn't find an explicit forward number in the latest transcript I could read.</p></section>`;
  return `<section class="section"><div class="idx">07 · Guidance</div><h2>What they are saying now</h2>${items.map((item) => `<p class="quote">“${esc(item.text)}”</p><p class="source">${esc(item.source)}</p>`).join("")}</section>`;
}
function sectionCases(memo) {
  const side = (items, cls) => (items || []).length ? `<div class="${cls}">${items.map((item) => `<div class="case"><p>${esc(item.text)}</p><p class="source">${esc(item.source)}</p></div>`).join("")}</div>` : `<p class="note">${cls === "for" ? "The statements don't support a stronger case than the trajectory above." : "Nothing in the statements I read is a clean case against."}</p>`;
  return `<section class="section"><div class="idx">08 · Bull and bear</div><h2>The case, both ways</h2>${side(memo.bull, "for")}${side(memo.bear, "against")}</section>`;
}
function sectionContacts(memo) {
  const contacts = memo.contacts || [];
  if (!contacts.length) return `<section class="section"><div class="idx">Who</div><h2>Nobody in the notebook</h2><p class="note">No employment, supplier, or theme overlap. That is a finding, not an empty state.</p></section>`;
  return `<section class="section"><div class="idx">Who</div><h2>Who can tell you more</h2>${contacts.map((contact) => `<button class="who-block" data-act="person" data-id="${esc(contact.id)}" style="display:block;width:100%"><div class="strength">${esc(strengthLabel(contact.strength))}</div><strong>${esc(contact.name)}</strong><p>${esc((contact.reasons || []).join(" "))}</p></button>`).join("")}</section>`;
}
function sectionAsk(memo) {
  const answer = state.asking ? `<p class="quiet">Looking only at the pages loaded for ${esc(memo.name)}.</p>` : state.ask ? `<p class="answer ${state.ask.refused ? "refused" : ""}">${esc(state.ask.answer)}</p>${(state.ask.quotes || []).map((quote) => `<p class="quote">“${esc(quote.text)}”</p><p class="source">${esc(quote.source || "")}</p>`).join("")}` : "";
  return `<section class="section"><div class="idx">Ask</div><h2>Ask the filings</h2><form class="ask" data-act="ask"><input name="q" placeholder="What did they say about margins?" autocomplete="off" enterkeyhint="search"><button type="submit" class="aside">Ask the pages</button></form>${answer}</section>`;
}
function sectionSources(memo) {
  const items = (memo.sources || []).map((source) => `<p class="note"><a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.label)}</a>${source.note ? " · " + esc(source.note) : ""}</p>`).join("");
  const warnings = (memo.warnings || []).map((item) => `<p class="note">${esc(item)}</p>`).join("");
  return `<section class="section"><div class="idx">Sources</div><h2>Primary only</h2>${items}${warnings}<p class="fineprint">No news, no broker notes, and nothing from the model's memory of this company. If a sentence isn't in the documents above, it isn't here.</p></section>`;
}
function signedPct(value) {
  if (value == null) return "";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return sign + Math.abs(value).toFixed(1) + "%";
}

function renderPeople() {
  if (state.person) return renderPerson();
  if (state.loading && !state.network) return `<div class="page"><p class="status">${esc(state.loading)}</p></div>`;
  const net = state.network || { expertise: [], results: [], calls: [] };
  const results = (net.results || []).map((person) => `<button class="row" data-act="person" data-id="${esc(person.id)}"><span>${esc(person.name)}<span class="sub">${esc(person.title)}</span></span></button>`).join("");
  const themes = (net.expertise || []).map((group) => `<div class="quarter"><h3>${esc(group.theme)}</h3>${group.people.map((person) => `<button class="row" data-act="person" data-id="${esc(person.id)}"><span>${esc(person.name)}<span class="sub">${esc(person.title)}</span></span></button>`).join("")}</div>`).join("");
  const calls = state.query && net.calls ? "" : "";
  return `<div class="page">
    <header class="mast"><div class="mark">FINN</div></header>
    <p class="lede">Who in the notebook can tell you something the filing can't.</p>
    <p class="quiet">${esc(net.reconnect_hint || "")}</p>
    <form class="search" data-act="search"><input name="q" value="${esc(state.query)}" placeholder="Specialty chemicals, or a name" autocomplete="off"></form>
    ${results ? `<p class="kicker">Matches</p>${results}` : ""}
    ${calls}
    <p class="kicker">By theme</p>
    ${themes}
    <p class="fineprint">Every profile in this notebook is synthetic. Built so the demo overlaps the book. A real deployment would take a notebook the investor uploads, not a scrape of a social network. Link strength is labelled because a shared employer is not an introduction.</p>
  </div>`;
}

function renderPerson() {
  const wrap = state.person || {};
  const person = wrap.person;
  if (!person) return `<div class="page"><p class="status">Missing.</p></div>`;
  const roles = (person.roles || []).map((role) => `<li><b>${esc(role.from)}–${role.to || "now"}</b> · ${esc(role.title)}, ${esc(role.org)}</li>`).join("");
  const recent = (wrap.recent || []).map((item) => `<p class="note">${esc(item.symbol)} · ${esc((item.text || item.desc || "").slice(0, 160))}</p>`).join("");
  return `<div class="page">
    <button class="back" data-act="close-person">The notebook</button>
    <p class="kicker">Synthetic profile</p>
    <h1 class="name">${esc(person.name)}</h1>
    <p>${esc(person.met_note || "")}</p>
    <p class="note">Last spoke ${esc(person.last_touch || "—")}. ${esc(person.last_note || "")}</p>
    <p class="kicker">Path</p>
    <ul class="person-path">${roles}</ul>
    ${recent ? `<p class="kicker">Recent filings at places they've worked</p>${recent}` : ""}
  </div>`;
}

function renderSettings() {
  const price = state.price;
  const volume = state.volume;
  const toggles = WAKE_ALL.map(([key, label]) => {
    const on = state.wake.includes(key);
    return `<button class="row" data-act="wake" data-key="${key}"><span>${esc(label)}</span><span class="toggle ${on ? "on" : ""}">${on ? "Wakes you" : "Filed"}</span></button>`;
  }).join("");
  return `<div class="page">
    <button class="back" data-act="close-settings">Back to the brief</button>
    <h1 class="name">What wakes you</h1>
    <p class="quiet">You decide what unusual means. The desk only watches.</p>
    <div class="row"><span>Price move, one day</span><span class="stepper"><button data-act="price" data-dir="-1">−</button><b class="num">${price}%</b><button data-act="price" data-dir="1">+</button></span></div>
    <div class="row"><span>Volume vs recent average</span><span class="stepper"><button data-act="volume" data-dir="-1">−</button><b class="num">${volume.toFixed(1)}×</b><button data-act="volume" data-dir="1">+</button></span></div>
    <p class="kicker">Categories</p>
    ${toggles}
  </div>`;
}

app.addEventListener("click", (event) => {
  const el = event.target.closest("[data-act]");
  if (!el || el.tagName === "FORM") return;
  const act = el.dataset.act;
  if (act === "view") {
    state.view = el.dataset.view;
    state.settings = false;
    state.person = null;
    if (state.view === "people") openPeople();
    else if (state.view === "company") { state.memo = null; render(); }
    else render();
  } else if (act === "window") {
    state.window = el.dataset.window;
    save();
    loadBrief();
  } else if (act === "toggle") {
    state.open[el.dataset.id] = !state.open[el.dataset.id];
    render();
  } else if (act === "away") {
    state.away = !state.away;
    render();
  } else if (act === "company") {
    loadMemo(el.dataset.symbol);
  } else if (act === "live") {
    loadMemo(el.dataset.symbol, true);
  } else if (act === "person") {
    loadPerson(el.dataset.id);
  } else if (act === "settings") {
    state.settings = true;
    render();
  } else if (act === "close-settings") {
    state.settings = false;
    render();
  } else if (act === "close-person") {
    state.person = null;
    render();
  } else if (act === "clear-memo") {
    state.memo = null;
    state.ask = null;
    render();
  } else if (act === "price") {
    state.price = Math.min(15, Math.max(1, state.price + Number(el.dataset.dir)));
    save();
    render();
    loadBrief();
  } else if (act === "volume") {
    state.volume = Math.round(Math.min(6, Math.max(1.5, state.volume + 0.5 * Number(el.dataset.dir))) * 10) / 10;
    save();
    render();
    loadBrief();
  } else if (act === "wake") {
    const key = el.dataset.key;
    state.wake = state.wake.includes(key) ? state.wake.filter((item) => item !== key) : state.wake.concat(key);
    save();
    render();
    loadBrief();
  }
});

app.addEventListener("submit", (event) => {
  const form = event.target.closest("form");
  if (!form) return;
  event.preventDefault();
  const value = new FormData(form).get("q") || "";
  if (form.dataset.act === "ask") ask(String(value));
  else if (form.dataset.act === "search") { state.query = String(value); openPeople(); }
  else route(String(value));
});

loadBrief();
