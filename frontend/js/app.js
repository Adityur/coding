/* Swing Watchlist AI - single-page frontend. All market values come from the API; nothing is hardcoded. */
(function () {
  const API = window.SwingAPI;
  const view = document.getElementById("view");
  const state = { config: null, health: null, wl: null, sort: { key: "rank", dir: "asc" }, filters: { q: "", signal: "", sector: "", min: "" },
    group: "overview", chart: null, stream: null, refreshTimer: null, stock: null };

  const SCORE_LABELS = { trend_score: "Trend", price_score: "Price", volume_score: "Volume", entry_score: "Entry", rr_score: "Risk/Reward",
    fundamental_score: "Fundamental", sector_score: "Sector", news_score: "News", fno_score: "F&O" };

  // ---------- formatting (every dynamic value passes through esc) ----------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const DASH = '<span class="muted">–</span>';
  const num = (v, d = 2) => (v == null || isNaN(v) ? DASH : `<span class="num">${Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}</span>`);
  const int = (v) => (v == null ? DASH : `<span class="num">${Math.round(v).toLocaleString("en-IN")}</span>`);
  const signed = (v, d = 2, suffix = "%") => (v == null ? DASH : `<span class="num ${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${v > 0 ? "+" : ""}${Number(v).toFixed(d)}${suffix}</span>`);
  const yn = (v) => (v == null ? DASH : v ? '<span class="yes">✓</span>' : '<span class="no">✗</span>');
  const txt = (v) => (v == null || v === "" ? DASH : esc(v));
  const score = (v) => { if (v == null) return '<span class="score na">–</span>'; const c = v >= 65 ? "hi" : v >= 45 ? "mid" : "lo"; return `<span class="score ${c}">${Math.round(v)}</span>`; };
  const pill = (s) => (s ? `<span class="pill ${esc(s)}">${esc(s)}</span>` : DASH);
  const time = (iso) => { if (!iso) return "–"; try { return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) + " IST"; } catch (e) { return esc(iso); } };
  const hyp = (r, html) => (r.signal === "BUY" ? html : `<span class="muted" title="Hypothetical level - signal is not BUY">${html}</span>`);
  const label = (s) => (s == null ? DASH : esc(String(s).replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())));

  // ---------- watchlist columns ----------
  const COLS = [
    { k: "rank", l: "#", g: "all", f: (r) => int(r.rank) },
    { k: "symbol", l: "Symbol", g: "all", cls: "text", f: (r) => `<span class="sym">${esc(r.symbol)}<small>${esc(r.sector || "")}</small></span>` },
    { k: "price", l: "Price", g: "all", f: (r) => `<span data-q="${esc(r.symbol)}:price">${num(r.price)}</span>` },
    { k: "change_pct", l: "Chg %", g: "all", f: (r) => `<span data-q="${esc(r.symbol)}:chg">${signed(r.change_pct)}</span>` },
    { k: "signal", l: "Signal", g: "all", f: (r) => pill(r.signal) },
    { k: "rating", l: "Rating", g: "overview", f: (r) => txt(r.rating) },
    { k: "total_score", l: "Total", g: "overview scores", f: (r) => score(r.total_score) },
    { k: "average_score", l: "Avg", g: "overview scores", f: (r) => score(r.average_score) },
    { k: "confidence", l: "Conf.", g: "overview", f: (r) => (r.confidence == null ? DASH : `<span class="num">${r.confidence}%</span>`) },
    { k: "trend", l: "Trend", g: "overview technical", f: (r) => label(r.trend) },
    { k: "pattern", l: "Breakout / pattern", g: "overview technical", cls: "text", f: (r) => txt(r.pattern || (r.breakout && r.breakout !== "NONE" ? r.breakout : null)) },
    { k: "price_score", l: "Price", g: "scores", f: (r) => score(r.price_score) },
    { k: "trend_score", l: "Trend", g: "scores", f: (r) => score(r.trend_score) },
    { k: "volume_score", l: "Volume", g: "scores", f: (r) => score(r.volume_score) },
    { k: "entry_score", l: "Entry", g: "scores", f: (r) => score(r.entry_score) },
    { k: "rr_score", l: "R:R", g: "scores", f: (r) => score(r.rr_score) },
    { k: "fundamental_score", l: "Fund.", g: "scores", f: (r) => score(r.fundamental_score) },
    { k: "sector_score", l: "Sector", g: "scores", f: (r) => score(r.sector_score) },
    { k: "news_score", l: "News", g: "scores", f: (r) => score(r.news_score) },
    { k: "fno_score", l: "F&O", g: "scores", f: (r) => score(r.fno_score) },
    { k: "hh_daily", l: "HH D", g: "technical", f: (r) => yn(r.hh_daily) },
    { k: "hh_hourly", l: "HH 1h", g: "technical", f: (r) => yn(r.hh_hourly) },
    { k: "hh_15m", l: "HH 15m", g: "technical", f: (r) => yn(r.hh_15m) },
    { k: "hh_5m", l: "HH 5m", g: "technical", f: (r) => yn(r.hh_5m) },
    { k: "higher_low", l: "HL D", g: "technical", f: (r) => yn(r.higher_low) },
    { k: "high_zone", l: "High zone", g: "technical", f: (r) => yn(r.high_zone) },
    { k: "pct_from_52w_high", l: "% off 52w H", g: "technical", f: (r) => num(r.pct_from_52w_high, 1) },
    { k: "ma20", l: "MA20", g: "technical", f: (r) => num(r.ma20) },
    { k: "ma50", l: "MA50", g: "technical", f: (r) => num(r.ma50) },
    { k: "ma200", l: "MA200", g: "technical", f: (r) => num(r.ma200) },
    { k: "ma_crossover", l: "MA cross", g: "technical", cls: "text", f: (r) => label(r.ma_crossover) },
    { k: "ma_slope_angle", l: "MA20 angle°", g: "technical", f: (r) => num(r.ma_slope_angle, 1) },
    { k: "volume_ratio", l: "Vol ×avg", g: "technical", f: (r) => num(r.volume_ratio) },
    { k: "volume", l: "Volume", g: "technical", f: (r) => int(r.volume) },
    { k: "relative_strength", l: "RS 20d", g: "technical", f: (r) => num(r.relative_strength, 3) },
    { k: "rsi14", l: "RSI", g: "technical", f: (r) => num(r.rsi14, 1) },
    { k: "mtf_alignment", l: "MTF", g: "technical", cls: "text", f: (r) => label(r.mtf_alignment) },
    { k: "roe", l: "ROE %", g: "fundamentals", f: (r) => num(r.roe, 1) },
    { k: "roe_growth", l: "ROE Δ", g: "fundamentals", f: (r) => signed(r.roe_growth, 1, "") },
    { k: "sales_growth", l: "Sales g %", g: "fundamentals", f: (r) => signed(r.sales_growth, 1) },
    { k: "profit_growth", l: "Profit g %", g: "fundamentals", f: (r) => signed(r.profit_growth, 1) },
    { k: "pe", l: "PE", g: "fundamentals", f: (r) => num(r.pe, 1) },
    { k: "fii_change", l: "FII Δ", g: "fundamentals", f: (r) => signed(r.fii_change) },
    { k: "dii_change", l: "DII Δ", g: "fundamentals", f: (r) => signed(r.dii_change) },
    { k: "oi_change_pct", l: "OI Δ %", g: "fundamentals", f: (r) => signed(r.oi_change_pct) },
    { k: "fno_buildup", l: "OI buildup", g: "fundamentals", cls: "text", f: (r) => label(r.fno_buildup) },
    { k: "news_catalyst", l: "News / catalyst", g: "fundamentals", cls: "text wrap", f: (r) => txt(r.news_catalyst) },
    { k: "entry", l: "Entry", g: "risk overview", f: (r) => hyp(r, num(r.entry)) },
    { k: "stop_loss", l: "Stop", g: "risk overview", f: (r) => hyp(r, num(r.stop_loss)) },
    { k: "target", l: "Target", g: "risk overview", f: (r) => hyp(r, num(r.target)) },
    { k: "risk_reward", l: "R:R", g: "risk overview", f: (r) => hyp(r, num(r.risk_reward)) },
    { k: "ai_remark", l: "AI remark", g: "overview risk", cls: "text wrap", f: (r) => txt(r.ai_remark) },
    { k: "data_source", l: "Source", g: "meta", cls: "text", f: (r) => txt(r.data_source) },
    { k: "timestamp", l: "Data time", g: "meta", cls: "text", f: (r) => esc(time(r.timestamp)) },
    { k: "data_quality", l: "Data quality", g: "meta", cls: "text", f: (r) => label(r.data_quality) },
  ];
  const GROUPS = [["overview", "Overview"], ["scores", "Scores"], ["technical", "Technical"], ["fundamentals", "Fundamental / News / F&O"], ["risk", "Risk"], ["meta", "Source"], ["allcols", "All"]];
  const visibleCols = () => COLS.filter((c) => state.group === "allcols" || c.g.split(" ").some((g) => g === "all" || g === state.group));

  // ---------- chrome ----------
  function setModeBadge() {
    const b = document.getElementById("mode-badge");
    const h = state.health, cfg = state.config;
    if (!h) { b.className = "badge down"; b.lastElementChild.textContent = "Server offline"; return; }
    const p = h.provider || {};
    if (h.demo_mode) { b.className = "badge demo"; b.lastElementChild.textContent = "DEMO data"; b.title = "Synthetic demo data - not live prices"; }
    else if (p.last_error && !p.connected) { b.className = "badge down"; b.lastElementChild.textContent = `${p.provider} unavailable`; b.title = p.last_error; }
    else { b.className = "badge live"; b.lastElementChild.textContent = `LIVE · ${p.provider}`; b.title = "Live provider configured"; }
    if (cfg) b.title += ` | AI: ${cfg.ai.engine}`;
  }
  function setLiveBadge(st, msg) {
    const b = document.getElementById("live-badge");
    b.classList.toggle("hidden", st === "off");
    b.className = "badge " + (st === "on" ? "live" : st === "off" ? "hidden" : "down");
    b.lastElementChild.textContent = st === "on" ? "Quotes streaming" : st === "reconnecting" ? "Reconnecting…" : "Quote error";
    b.title = msg || "";
  }
  function activeNav(name) { document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name)); }

  function applyTheme() {
    const t = API.loadPrefs().theme;
    if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
  }
  document.getElementById("theme-btn").addEventListener("click", () => {
    const p = API.loadPrefs();
    const dark = p.theme === "dark" || (p.theme === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    p.theme = dark ? "light" : "dark"; API.savePrefs(p); applyTheme(); if (state.chart) state.chart.draw();
  });

  async function loadStatus() {
    try { [state.health, state.config] = await Promise.all([API.get("/health"), API.get("/api/config")]); }
    catch (e) { state.health = null; state.config = null; }
    setModeBadge();
  }

  function errorBox(e) {
    const settingsHint = e.code === "no_api_base" || e.code === "network_error" ? ' <a href="#/settings">Open Settings</a>' : "";
    return `<div class="banner error"><b>${esc(e.code || "error")}</b>: ${esc(e.message)}${settingsHint}</div>`;
  }

  function modeBanner(data) {
    if (!data) return "";
    if (!data.is_live) return `<div class="banner"><b>DEMO MODE</b> — prices, fundamentals and news are synthetic and deterministic. They are <b>not</b> live market data. Set <code>DEMO_MODE=false</code> with SAMCO credentials for live data.</div>`;
    return "";
  }

  // ---------- watchlist ----------
  function filteredRows() {
    const f = state.filters, q = f.q.trim().toUpperCase();
    let rows = (state.wl && state.wl.rows) || [];
    rows = rows.filter((r) => (!q || r.symbol.includes(q) || (r.name || "").toUpperCase().includes(q))
      && (!f.signal || r.signal === f.signal) && (!f.sector || r.sector === f.sector)
      && (f.min === "" || (r.total_score != null && r.total_score >= Number(f.min))));
    const { key, dir } = state.sort;
    const present = rows.filter((r) => r[key] != null), absent = rows.filter((r) => r[key] == null);
    present.sort((a, b) => { const x = a[key], y = b[key]; const c = typeof x === "string" ? x.localeCompare(y) : x - y; return dir === "asc" ? c : -c; });
    return present.concat(absent);
  }

  function renderWatchlistBody() {
    const rows = filteredRows(), cols = visibleCols();
    const thead = cols.map((c) => `<th class="${c.cls || ""} ${state.sort.key === c.k ? "sorted" : ""}" data-sort="${c.k}">${esc(c.l)}${state.sort.key === c.k ? (state.sort.dir === "asc" ? " ▲" : " ▼") : ""}</th>`).join("");
    const tbody = rows.map((r) => r.error
      ? `<tr data-sym="${esc(r.symbol)}"><td>${DASH}</td><td class="text"><span class="sym">${esc(r.symbol)}</span></td><td colspan="${cols.length - 2}" class="text neg">${esc(r.error)}</td></tr>`
      : `<tr data-sym="${esc(r.symbol)}">${cols.map((c) => `<td class="${c.cls || ""}">${c.f(r)}</td>`).join("")}</tr>`).join("");
    document.getElementById("wl-table").innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${tbody || `<tr><td colspan="${cols.length}" class="empty">No stocks match the filters.</td></tr>`}</tbody></table>`;
    document.getElementById("wl-cards").innerHTML = rows.map((r) => r.error
      ? `<div class="mcard" data-sym="${esc(r.symbol)}"><div class="row1"><span class="sym">${esc(r.symbol)}</span><span class="neg small">${esc(r.error)}</span></div></div>`
      : `<div class="mcard" data-sym="${esc(r.symbol)}">
          <div class="row1"><span class="sym">${int(r.rank)} · ${esc(r.symbol)}<small>${esc(r.name || "")} · ${esc(r.sector || "")}</small></span>
            <span style="text-align:right"><span data-q="${esc(r.symbol)}:price">${num(r.price)}</span><br><span data-q="${esc(r.symbol)}:chg">${signed(r.change_pct)}</span></span></div>
          <div class="row1" style="margin-top:6px">${pill(r.signal)}<span class="small muted">${esc(r.rating || "")} · conf ${r.confidence ?? "–"}%</span>${score(r.total_score)}</div>
          <div class="grid"><div>Trend<b>${label(r.trend)}</b></div><div>Entry<b>${num(r.entry)}</b></div><div>Stop<b>${num(r.stop_loss)}</b></div>
            <div>Target<b>${num(r.target)}</b></div><div>R:R<b>${num(r.risk_reward)}</b></div><div>HH D/1h<b>${yn(r.hh_daily)} ${yn(r.hh_hourly)}</b></div></div>
          <div class="remark">${txt(r.ai_remark)}</div></div>`).join("") || '<div class="empty">No stocks match the filters.</div>';
    document.getElementById("wl-count").textContent = `${rows.length} of ${(state.wl && state.wl.rows.length) || 0} stocks`;
  }

  function renderWatchlistShell() {
    const wl = state.wl;
    const sectors = [...new Set((wl.rows || []).map((r) => r.sector).filter(Boolean))].sort();
    const scored = wl.rows.filter((r) => r.total_score != null);
    const top = scored.slice().sort((a, b) => b.total_score - a.total_score)[0];
    const avg = scored.length ? scored.reduce((s, r) => s + r.total_score, 0) / scored.length : null;
    view.innerHTML = `
      ${modeBanner(wl)}
      ${wl.errors && wl.errors.length ? `<div class="banner error">${wl.errors.length} symbol(s) failed to load: ${esc(wl.errors.slice(0, 3).map((e) => e.symbol + " – " + e.error).join("; "))}</div>` : ""}
      <section class="cards">
        <div class="card"><div class="label">Buy signals</div><div class="value buy">${wl.summary.BUY}</div></div>
        <div class="card"><div class="label">Hold</div><div class="value hold">${wl.summary.HOLD}</div></div>
        <div class="card"><div class="label">Sell / avoid</div><div class="value sell">${wl.summary.SELL}</div></div>
        <div class="card"><div class="label">Avg score</div><div class="value">${avg == null ? "–" : avg.toFixed(1)}</div></div>
        <div class="card"><div class="label">Top ranked</div><div class="value" style="font-size:18px">${top ? `<a href="#/stock/${encodeURIComponent(top.symbol)}">${esc(top.symbol)}</a> ${score(top.total_score)}` : "–"}</div></div>
      </section>
      <div class="filters">
        <input id="f-q" type="search" placeholder="Filter, or type any NSE symbol + Enter" value="${esc(state.filters.q)}" aria-label="Search">
        <select id="f-signal" aria-label="Signal"><option value="">All signals</option>${["BUY", "HOLD", "SELL"].map((s) => `<option ${state.filters.signal === s ? "selected" : ""}>${s}</option>`).join("")}</select>
        <select id="f-sector" aria-label="Sector"><option value="">All sectors</option>${sectors.map((s) => `<option ${state.filters.sector === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <input id="f-min" type="number" min="0" max="100" placeholder="Min score" style="width:110px" value="${esc(state.filters.min)}" aria-label="Minimum score">
        <div class="seg cols">${GROUPS.map(([k, l]) => `<button data-group="${k}" class="${state.group === k ? "active" : ""}">${l}</button>`).join("")}</div>
        <div class="spacer"></div>
        <button id="wl-refresh" class="btn">↻ Refresh</button>
      </div>
      <div class="meta-line"><span id="wl-count"></span> · Source: <b>${esc(wl.data_source)}</b> · Scores computed ${esc(time(wl.generated_at))} · Capital ₹${Number(wl.capital).toLocaleString("en-IN")} @ ${wl.risk_pct}% risk · <span id="wl-quote-time"></span></div>
      <div id="wl-table" class="table-wrap desktop-only"></div>
      <div id="wl-cards" class="mcards"></div>
      <p class="disclaimer">Decision support only — signals are rule-based evaluations of the data shown, not investment advice. This app never places orders.</p>`;
    renderWatchlistBody();
    const rerender = () => renderWatchlistBody();
    document.getElementById("f-q").addEventListener("input", (e) => { state.filters.q = e.target.value; rerender(); });
    document.getElementById("f-q").addEventListener("keydown", (e) => {
      const sym = e.target.value.trim().toUpperCase();
      if (e.key === "Enter" && /^[A-Z0-9&-]{1,20}$/.test(sym)) location.hash = "#/stock/" + encodeURIComponent(sym);
    });
    document.getElementById("f-signal").addEventListener("change", (e) => { state.filters.signal = e.target.value; rerender(); });
    document.getElementById("f-sector").addEventListener("change", (e) => { state.filters.sector = e.target.value; rerender(); });
    document.getElementById("f-min").addEventListener("input", (e) => { state.filters.min = e.target.value; rerender(); });
    document.querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => { state.group = b.dataset.group; document.querySelectorAll("[data-group]").forEach((x) => x.classList.toggle("active", x === b)); rerender(); }));
    document.getElementById("wl-refresh").addEventListener("click", () => loadWatchlist(true));
    view.addEventListener("click", onWatchlistClick);
  }

  function onWatchlistClick(e) {
    const th = e.target.closest("th[data-sort]");
    if (th) { const k = th.dataset.sort; state.sort = { key: k, dir: state.sort.key === k && state.sort.dir === "asc" ? "desc" : (k === "rank" || k === "symbol" ? "asc" : "desc") }; renderWatchlistBody(); return; }
    const row = e.target.closest("[data-sym]");
    if (row && !e.target.closest("a")) location.hash = "#/stock/" + encodeURIComponent(row.dataset.sym);
  }

  async function loadWatchlist(manual) {
    const btn = document.getElementById("wl-refresh");
    if (btn) { btn.disabled = true; btn.textContent = "Refreshing…"; }
    const p = API.loadPrefs();
    try {
      state.wl = await API.get("/api/watchlist", { capital: p.capital, risk_pct: p.riskPct, limit: 500 });
      if (location.hash.startsWith("#/watchlist") || location.hash === "" || location.hash === "#/") { view.removeEventListener("click", onWatchlistClick); renderWatchlistShell(); startStream(); }
    } catch (e) {
      if (!state.wl || manual) view.innerHTML = errorBox(e);
    }
  }

  function startStream() {
    const p = API.loadPrefs();
    if (!p.liveQuotes || !state.wl) { stopStream(); return; }
    stopStream();
    state.stream = new API.QuoteStream(onQuotes, setLiveBadge);
    state.stream.start(state.wl.rows.filter((r) => !r.error).map((r) => r.symbol).slice(0, 50), 5);
  }
  function stopStream() { if (state.stream) state.stream.stop(); state.stream = null; }

  function onQuotes(quotes, t) {
    for (const q of quotes) {
      if (q.error) continue;
      const row = state.wl && state.wl.rows.find((r) => r.symbol === q.symbol);
      if (row) { row.price = q.ltp; row.change_pct = q.change_pct; }
      document.querySelectorAll(`[data-q="${CSS.escape(q.symbol)}:price"]`).forEach((el) => { const html = num(q.ltp); if (el.innerHTML !== html) { el.innerHTML = html; el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); } });
      document.querySelectorAll(`[data-q="${CSS.escape(q.symbol)}:chg"]`).forEach((el) => { el.innerHTML = signed(q.change_pct); });
      if (state.stock && state.stock.symbol === q.symbol) { const el = document.getElementById("stock-price"); if (el) el.innerHTML = num(q.ltp); }
    }
    const el = document.getElementById("wl-quote-time");
    if (el) el.textContent = "Prices updated " + time(t);
  }

  // ---------- stock page ----------
  function kv(pairs) { return `<div class="kv">${pairs.map(([k, v]) => `<div>${esc(k)}</div><div>${v}</div>`).join("")}</div>`; }
  const srcTag = (s, asOf) => `<span class="src muted">${esc(s || "UNAVAILABLE")}${asOf ? " · " + esc(asOf) : ""}</span>`;

  function scorePanel(a) {
    const rows = Object.entries(SCORE_LABELS).map(([k, l]) => {
      const card = a.scores[k] || {}, v = card.score;
      const color = v == null ? "var(--muted)" : v >= 65 ? "var(--buy)" : v >= 45 ? "var(--hold)" : "var(--sell)";
      const factors = (card.factors || []).map((f) => `<tr><td>${esc(f.name)}${f.note ? ` <span class="muted">(${esc(f.note)})</span>` : ""}</td><td>${f.value == null ? "n/a" : esc(typeof f.value === "object" ? Object.entries(f.value).map(([x, y]) => x + "=" + y).join(", ") : f.value)}</td><td>${f.points == null ? "–" : esc(f.points)}/${esc(f.max)}</td></tr>`).join("");
      const weight = a.decision.weights_used && a.decision.weights_used[k];
      return `<div class="bar-row" data-toggle="${k}"><span>${esc(l)}${weight ? ` <span class="muted small">${Math.round(weight * 100)}%</span>` : ""}</span><span class="bar"><i style="width:${v || 0}%;background:${color}"></i></span>${score(v)}</div>
        <table class="factors hidden" id="fx-${k}"><tbody>${factors || '<tr><td class="muted">No factors.</td></tr>'}${card.not_applicable ? '<tr><td class="muted">Not F&O eligible - excluded.</td></tr>' : ""}</tbody></table>`;
    }).join("");
    const ci = a.decision.confidence_inputs || {};
    return `<div class="panel"><h2>Score breakdown <span class="src muted">click a row for factors</span></h2>${rows}
      <p class="small muted">Total = weighted mean of available scores (weights renormalised). Confidence ${a.decision.confidence}% from coverage ${ci.coverage ?? "–"}, agreement ${ci.agreement ?? "–"}, conviction ${ci.conviction ?? "–"}, data quality ×${ci.data_quality_factor ?? "–"}.</p></div>`;
  }

  function riskPanel(a) {
    const r = a.risk, pos = r.position || {}, p = API.loadPrefs();
    const isBuy = a.decision.signal === "BUY";
    return `<div class="panel"><h2>Risk plan ${isBuy ? "" : '<span class="src muted">hypothetical — signal is not BUY</span>'}</h2>
      ${kv([["Entry", num(r.entry)], ["Stop loss", num(r.stop_loss) + (r.stop_pct != null ? ` <span class="muted small">(${r.stop_pct}%)</span>` : "")], ["Target", num(r.target)], ["Target 2 (3R)", num(r.target_2)],
        ["Risk / share", num(r.risk_per_share)], ["Reward / share", num(r.reward_per_share)], ["Risk : reward", num(r.risk_reward)], ["Stop method", txt(r.stop_method)], ["Target method", txt(r.target_method)],
        ["Quantity", int(pos.quantity)], ["Position value", num(pos.position_value)], ["Max loss at stop", num(pos.max_loss_at_stop)]])}
      ${r.exit_levels && r.exit_levels.trailing_stop ? `<p class="small">Holders: protective trailing stop ${num(r.exit_levels.trailing_stop)} <span class="muted">(${esc(r.exit_levels.method)})</span></p>` : ""}
      <form id="risk-form" class="filters" style="margin-top:10px">
        <label class="small muted">Capital ₹ <input id="r-cap" type="number" min="1" step="1000" style="width:130px" value="${esc(p.capital || (pos.capital || ""))}"></label>
        <label class="small muted">Risk % <input id="r-risk" type="number" min="0.1" max="5" step="0.1" style="width:80px" value="${esc(p.riskPct || (pos.risk_pct || ""))}"></label>
        <button class="btn" type="submit">Recalculate</button>
      </form>
      ${r.warnings && r.warnings.length ? `<ul class="clean small">${r.warnings.map((w) => `<li class="neg">${esc(w)}</li>`).join("")}</ul>` : ""}
      <p class="small muted">${esc(r.disclaimer)}</p></div>`;
  }

  function mtfPanel(a) {
    const rows = ["1d", "1h", "15m", "5m"].map((tf) => {
      const t = a.technical[tf];
      if (!t) return `<tr><td class="text">${tf}</td><td colspan="6" class="text muted">unavailable</td></tr>`;
      const st = t.structure || {}, m = t.momentum || {};
      return `<tr><td class="text"><b>${tf}</b></td><td class="text">${label(t.trend)}</td><td>${yn(st.higher_high)}</td><td>${yn(st.higher_low)}</td><td class="text">${label(t.ma_alignment)}</td><td>${num(m.rsi14, 1)}</td><td class="text">${label((t.data_quality || {}).status)}</td></tr>`;
    }).join("");
    return `<div class="panel"><h2>Multi-timeframe <span class="src muted">alignment: ${label(a.multi_timeframe.alignment)}</span></h2>
      <div style="overflow-x:auto"><table class="factors"><thead><tr><td>TF</td><td>Trend</td><td>HH</td><td>HL</td><td>MA align</td><td>RSI</td><td>Data</td></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  function techPanel(a) {
    const d = a.technical["1d"] || {}, ma = d.moving_averages || {}, m = d.momentum || {}, xo = d.ma_crossover || {}, sl = d.slope || {}, v = d.volume || {}, rs = d.relative_strength || {}, hz = d.high_zone || {}, b = d.breakout || {};
    return `<div class="panel"><h2>Technical (daily)</h2>${kv([
      ["SMA 20 / 50 / 200", `${num(ma.sma20)} / ${num(ma.sma50)} / ${num(ma.sma200)}`], ["EMA 9 / 21", `${num(ma.ema9)} / ${num(ma.ema21)}`],
      ["MA alignment", label(d.ma_alignment)], ["Crossover (EMA9/21)", label(xo.signal) + (xo.bars_ago != null ? ` <span class="muted small">${xo.bars_ago} bars ago</span>` : "")],
      ["Golden / death cross (10 bars)", `${yn(xo.golden_cross)} / ${yn(xo.death_cross)}`], ["SMA20 slope", `${num(sl.sma20_pct_per_bar, 3)}%/bar · ${num(sl.sma20_angle_deg, 1)}°`],
      ["SMA50 slope", `${num(sl.sma50_pct_per_bar, 3)}%/bar · ${num(sl.sma50_angle_deg, 1)}°`], ["RSI 14", num(m.rsi14, 1)], ["MACD hist", num(m.macd_hist, 3)], ["ROC 10", signed(m.roc10)],
      ["ATR 14", `${num(d.atr14)} <span class="muted small">(${d.atr_pct ?? "–"}%)</span>`], ["Breakout (20)", `${label(b.status)} @ ${num(b.level)}`], ["Pattern", txt(d.pattern)],
      ["Volume / 20d avg", `${int(v.last)} / ${int(v.avg20)} (${v.ratio ?? "–"}×)`], ["Up/down volume (20)", num(v.up_down_ratio20)],
      ["RS vs NIFTY 20d / 60d", `${num(rs.rs20, 3)} / ${num(rs.rs60, 3)}`], ["52w high / low", `${num(hz.high_52w)} / ${num(hz.low_52w)}`], ["% from 52w high", num(hz.pct_from_high, 1) + (hz.in_high_zone ? ' <span class="yes">high zone</span>' : "")],
      ["Support", d.support && d.support.length ? d.support.map((x) => num(x)).join(", ") : DASH], ["Resistance", d.resistance && d.resistance.length ? d.resistance.map((x) => num(x)).join(", ") : DASH],
    ])}</div>`;
  }

  function refPanels(a) {
    const f = a.reference.fundamentals, s = a.reference.shareholding, n = a.reference.news, o = a.reference.fno;
    const news = n.items && n.items.length ? `<ul class="clean">${n.items.map((i) => `<li>${esc(i.headline)} <span class="muted small">${esc(i.date || "")}${i.sentiment != null ? " · sentiment " + esc(i.sentiment) : ""}</span></li>`).join("")}</ul>` : '<p class="muted">No news data available.</p>';
    return `<div class="panel"><h2>Fundamentals ${srcTag(f.source, f.as_of)}</h2>${kv([["ROE %", num(f.roe, 1)], ["ROE growth (pp)", signed(f.roe_growth, 1, "")], ["Sales growth", signed(f.sales_growth, 1)], ["Profit growth", signed(f.profit_growth, 1)], ["PE / sector PE", `${num(f.pe, 1)} / ${num(f.sector_pe, 1)}`]])}
        <h2 style="margin-top:14px">Shareholding ${srcTag(s.source, s.as_of)}</h2>${kv([["FII change (pp)", signed(s.fii_change)], ["DII change (pp)", signed(s.dii_change)]])}</div>
      <div class="panel"><h2>News / catalyst ${srcTag(n.source, n.as_of)}</h2>${n.catalyst ? `<p><b>Catalyst:</b> ${esc(n.catalyst)}</p>` : ""}${news}<p class="small muted">Avg sentiment: ${n.sentiment ?? "n/a"}</p>
        <h2 style="margin-top:14px">F&amp;O / OI ${srcTag(o.source, o.as_of)}</h2>${o.eligible === false ? '<p class="muted">Not in F&amp;O segment.</p>' : kv([["Open interest", int(o.oi)], ["OI change", signed(o.oi_change_pct)], ["PCR", num(o.pcr)], ["Buildup", label(a.scores.fno_score.buildup)]])}</div>`;
  }

  function decisionPanel(a) {
    const d = a.decision;
    return `<div class="panel"><h2>Decision</h2>
      <p>${pill(d.signal)} <b>${esc(d.rating)}</b> · total ${score(d.total_score)} · avg ${score(d.average_score)} · confidence <b>${d.confidence}%</b></p>
      <p class="small"><b>Rule-based remark:</b> ${txt(a.ai_remark)}</p>
      ${d.reasons.length ? `<h2 style="margin-top:12px">Reasons</h2><ul class="clean small">${d.reasons.map((r) => `<li class="pos">${esc(r)}</li>`).join("")}</ul>` : ""}
      ${d.warnings.length ? `<h2 style="margin-top:12px">Warnings</h2><ul class="clean small">${d.warnings.map((r) => `<li class="neg">${esc(r)}</li>`).join("")}</ul>` : ""}
      <p class="small muted">BUY requires total ≥ 62, a non-down daily trend, R:R ≥ 1.5 and entry score ≥ 35. SELL = exit/avoid for holders (no short selling).</p></div>`;
  }

  function aiPanel() {
    return `<div class="panel" style="grid-column:1/-1"><h2>AI analysis <span class="src muted">${esc(state.config ? "engine: " + state.config.ai.engine + (state.config.ai.model ? " · " + state.config.ai.model : "") : "")}</span></h2>
      <div id="ai-body"><p class="muted">The AI reads only the structured data on this page and explains it. It does not fetch outside news or prices.</p>
      <button id="ai-run" class="btn primary">Run AI analysis</button></div></div>`;
  }

  function renderAI(r) {
    const ai = r.ai_interpretation, live = r.live_data, list = (xs) => (xs && xs.length ? `<ul class="clean">${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : '<p class="muted">None.</p>');
    const q = live.quote || {};
    document.getElementById("ai-body").innerHTML = `
      ${r.warnings && r.warnings.length ? `<div class="banner">${r.warnings.map(esc).join("<br>")}</div>` : ""}
      <div class="ai-section ${live.is_live ? "live" : "demo"}"><h3>${esc(live.label)}</h3><p class="small">${esc(r.symbol)} LTP ${num(q.ltp)} (${signed(q.change_pct)}) · source ${esc(live.data_source)} · ${esc(time(live.timestamp))}</p></div>
      <div class="ai-section calc"><h3>${esc(r.calculated_data.label)}</h3><p class="small">Signal ${pill(r.calculated_data.decision.signal)} · total ${score(r.calculated_data.decision.total_score)} · R:R ${num(r.calculated_data.risk.risk_reward)} · MTF ${label(r.calculated_data.multi_timeframe.alignment)} · reference sources: ${esc(Object.entries(r.reference_data.sources).map(([k, v]) => k + "=" + (v || "n/a")).join(", "))}</p></div>
      <div class="ai-section ai"><h3>${esc(ai.label)} · entry quality ${esc(ai.entry_quality)} · confidence ${esc(ai.confidence)}%</h3>
        <p><b>Setup:</b> ${esc(ai.setup_summary)}</p>
        <div class="grid2"><div><b class="pos">Bullish factors</b>${list(ai.bullish_factors)}</div><div><b class="neg">Bearish factors</b>${list(ai.bearish_factors)}</div></div>
        <p><b>Catalyst:</b> ${esc(ai.catalyst_interpretation)}</p><p><b>Trend:</b> ${esc(ai.trend_interpretation)}</p><p><b>Technical alignment:</b> ${esc(ai.technical_alignment)}</p>
        <b>Risk warnings</b>${list(ai.risk_warnings)}
        <p><b>Final assessment:</b> ${esc(ai.final_assessment)}</p></div>
      <p class="small muted">${esc(r.disclaimer)} Generated ${esc(time(r.generated_at))}.</p>
      <button id="ai-run" class="btn">Re-run</button>`;
    document.getElementById("ai-run").addEventListener("click", runAI);
  }

  async function runAI() {
    const btn = document.getElementById("ai-run");
    btn.disabled = true; btn.textContent = "Analysing…";
    try { renderAI(await API.get(`/api/stock/${encodeURIComponent(state.stock.symbol)}/ai`)); }
    catch (e) { document.getElementById("ai-body").innerHTML = errorBox(e) + '<button id="ai-run" class="btn">Retry</button>'; document.getElementById("ai-run").addEventListener("click", runAI); }
  }

  async function loadChart(tf) {
    document.querySelectorAll("[data-tf]").forEach((b) => b.classList.toggle("active", b.dataset.tf === tf));
    try {
      const d = await API.get(`/api/stock/${encodeURIComponent(state.stock.symbol)}/chart`, { timeframe: tf, limit: tf === "1d" ? 180 : 150 });
      if (state.chart) state.chart.setData(d);
      document.getElementById("chart-src").textContent = `${d.data_source} · ${time(d.timestamp)} · ${d.count} bars`;
    } catch (e) { document.getElementById("chart-src").textContent = e.message; if (state.chart) state.chart.setData(null); }
  }

  async function renderStock(symbol) {
    activeNav("");
    view.innerHTML = '<div class="loading">Analysing ' + esc(symbol) + "…</div>";
    const p = API.loadPrefs();
    let a;
    try { a = await API.get(`/api/stock/${encodeURIComponent(symbol)}`, { capital: p.capital, risk_pct: p.riskPct }); }
    catch (e) { view.innerHTML = `<p><a href="#/watchlist">← Watchlist</a></p>` + errorBox(e); return; }
    state.stock = a;
    const q = a.quote, d = a.decision;
    const ringColor = d.total_score >= 65 ? "var(--buy)" : d.total_score >= 45 ? "var(--hold)" : "var(--sell)";
    view.innerHTML = `
      <p><a href="#/watchlist">← Watchlist</a></p>
      ${modeBanner(a)}
      <section class="stock-head">
        <div><h1>${esc(a.symbol)}</h1><div class="muted">${esc(a.name || "")} · ${esc(a.sector || "")}${a.fno_eligible ? " · F&amp;O" : ""}</div></div>
        <div><div class="price" id="stock-price">${num(q.ltp)}</div><div>${signed(q.change, 2, "")} <span class="muted">abs</span> · ${signed(q.change_pct)}</div></div>
        <div class="ring" style="--v:${d.total_score || 0};--ring-color:${ringColor}" title="Total score"><span>${d.total_score == null ? "–" : Math.round(d.total_score)}</span></div>
        <div>${pill(d.signal)}<div class="small" style="margin-top:4px"><b>${esc(d.rating)}</b> · confidence ${d.confidence}%</div></div>
        <div class="spacer"></div>
        <div class="small muted" style="text-align:right">Source <b>${esc(a.data_source)}</b> (${a.is_live ? "live" : "not live"})<br>Data time ${esc(time(a.timestamp))}<br>Data quality: ${label(a.data_quality.overall)}</div>
      </section>
      <section class="panel chart-panel">
        <h2>Chart <span class="seg" style="text-transform:none">${["1d", "1h", "15m", "5m"].map((tf) => `<button data-tf="${tf}">${tf.toUpperCase()}</button>`).join("")}</span>
          <span class="legend">${Object.entries(window.CHART_COLORS).map(([k, c]) => `<span><i style="background:${c}"></i>${k.toUpperCase()}</span>`).join("")}</span>
          <span class="src muted" id="chart-src"></span></h2>
        <div class="chart-box" id="chart-box"></div>
      </section>
      <section class="grid2">
        ${decisionPanel(a)}${scorePanel(a)}${riskPanel(a)}${mtfPanel(a)}${techPanel(a)}${refPanels(a)}${aiPanel()}
      </section>
      <p class="disclaimer">Decision support only. Not investment advice. Past price structure does not guarantee future returns. This app does not place orders.</p>`;
    if (state.chart) state.chart.destroy();
    state.chart = new window.CandleChart(document.getElementById("chart-box"));
    document.querySelectorAll("[data-tf]").forEach((b) => b.addEventListener("click", () => loadChart(b.dataset.tf)));
    document.querySelectorAll("[data-toggle]").forEach((r) => r.addEventListener("click", () => document.getElementById("fx-" + r.dataset.toggle).classList.toggle("hidden")));
    document.getElementById("ai-run").addEventListener("click", runAI);
    bindRiskForm(a);
    loadChart("1d");
    stopStream();
    if (p.liveQuotes) { state.stream = new API.QuoteStream(onQuotes, setLiveBadge); state.stream.start([a.symbol], 5); }
  }
  function bindRiskForm(a) {
    document.getElementById("risk-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const cap = Number(document.getElementById("r-cap").value), risk = Number(document.getElementById("r-risk").value);
      try {
        const r = await API.get(`/api/stock/${encodeURIComponent(a.symbol)}/risk`, { capital: cap || null, risk_pct: risk || null });
        a.risk = Object.assign({}, a.risk, r.risk);
        document.getElementById("risk-form").closest(".panel").outerHTML = riskPanel(a);
        bindRiskForm(a);
      } catch (err) { alert(err.message); }
    });
  }

  // ---------- settings ----------
  function renderSettings() {
    activeNav("settings"); stopStream();
    const p = API.loadPrefs(), c = state.config, h = state.health;
    view.innerHTML = `
      <div class="grid2">
        <div class="panel"><h2>App settings <span class="src muted">stored on this device only</span></h2>
          <form id="settings" class="form">
            <label>Server address (leave empty when this page is served by the backend; required for the Android app)
              <input id="s-base" type="url" placeholder="http://192.168.1.10:8000" value="${esc(p.apiBase)}"></label>
            <label>Default capital (₹) <input id="s-cap" type="number" min="1" step="1000" placeholder="${esc(c ? c.default_capital : "500000")}" value="${esc(p.capital || "")}"></label>
            <label>Risk per trade (%) <input id="s-risk" type="number" min="0.1" max="5" step="0.1" placeholder="${esc(c ? c.default_risk_pct : "1")}" value="${esc(p.riskPct || "")}"></label>
            <label>Watchlist auto-refresh (seconds, min 30) <input id="s-ref" type="number" min="30" step="10" value="${esc(p.refreshSec)}"></label>
            <label><span><input id="s-live" type="checkbox" ${p.liveQuotes ? "checked" : ""}> Stream live quotes (WebSocket)</span></label>
            <div><button class="btn primary" type="submit">Save</button> <span id="s-msg" class="small muted"></span></div>
          </form></div>
        <div class="panel"><h2>Server status</h2>${h && c ? kv([["Mode", esc(c.mode)], ["Provider", esc(h.provider.provider)], ["Provider connected", yn(h.provider.connected)],
            ["Provider last error", txt(h.provider.last_error)], ["SAMCO credentials configured", yn(c.samco_credentials_configured)], ["AI engine", esc(c.ai.engine) + (c.ai.model ? " · " + esc(c.ai.model) : "")],
            ["Timeframes", esc(c.timeframes.join(", "))], ["Order execution", '<span class="muted">disabled (decision support only)</span>'], ["Server time", esc(time(h.time))]])
          : '<p class="neg">Server not reachable at the configured address.</p>'}
          <p class="small muted">Credentials (SAMCO, Anthropic) are set only in the server's <code>.env</code> file and are never sent to this app.</p></div>
        <div class="panel"><h2>Watchlist symbols</h2>
          <form id="wl-form" class="form"><label>Comma-separated NSE symbols (empty list resets to the default universe file)
            <input id="wl-syms" type="text" placeholder="loading…"></label>
            <div><button class="btn" type="submit">Save watchlist</button> <span id="wl-msg" class="small muted"></span></div></form></div>
      </div>`;
    API.get("/api/watchlist/symbols").then((r) => { document.getElementById("wl-syms").value = r.symbols.join(", "); }).catch(() => {});
    document.getElementById("settings").addEventListener("submit", async (e) => {
      e.preventDefault();
      const np = Object.assign(API.loadPrefs(), {
        apiBase: document.getElementById("s-base").value.trim(), capital: Number(document.getElementById("s-cap").value) || null,
        riskPct: Number(document.getElementById("s-risk").value) || null, refreshSec: Math.max(30, Number(document.getElementById("s-ref").value) || 60),
        liveQuotes: document.getElementById("s-live").checked });
      API.savePrefs(np); state.wl = null; await loadStatus(); scheduleRefresh();
      document.getElementById("s-msg").textContent = state.health ? "Saved. Connected." : "Saved, but the server is not reachable.";
    });
    document.getElementById("wl-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const syms = document.getElementById("wl-syms").value.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
      const msg = document.getElementById("wl-msg");
      if (!syms.length) { msg.textContent = "Enter at least one symbol."; return; }
      try { const r = await API.put("/api/watchlist/symbols", { symbols: syms }); msg.textContent = `Saved ${r.symbols.length} symbols.`; state.wl = null; }
      catch (err) { msg.textContent = err.message; }
    });
  }

  // ---------- routing ----------
  function scheduleRefresh() {
    clearInterval(state.refreshTimer);
    const sec = Math.max(30, API.loadPrefs().refreshSec || 60);
    state.refreshTimer = setInterval(() => { if (!location.hash || location.hash.startsWith("#/watchlist")) loadWatchlist(false); }, sec * 1000);
  }

  async function route() {
    const hash = location.hash || "#/watchlist";
    view.removeEventListener("click", onWatchlistClick);
    if (state.chart && !hash.startsWith("#/stock/")) { state.chart.destroy(); state.chart = null; }
    if (hash.startsWith("#/stock/")) { renderStock(decodeURIComponent(hash.slice(8)).toUpperCase()); return; }
    if (hash.startsWith("#/settings")) { renderSettings(); return; }
    activeNav("watchlist"); state.stock = null;
    if (state.wl) { view.removeEventListener("click", onWatchlistClick); renderWatchlistShell(); startStream(); }
    else { view.innerHTML = '<div class="loading">Loading watchlist…</div>'; await loadWatchlist(true); }
  }

  window.addEventListener("hashchange", route);
  applyTheme();
  loadStatus().then(() => {
    if (API.base() === null) { location.hash = "#/settings"; }
    route(); scheduleRefresh();
  });
  if ("serviceWorker" in navigator && (location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(location.hostname))) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
})();
