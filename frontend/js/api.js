/* API client: base URL resolution, JSON fetch with structured errors, and a reconnecting quote socket. */
(function () {
  const PREFS_KEY = "swing.prefs.v1";
  const defaults = { apiBase: "", capital: null, riskPct: null, refreshSec: 60, liveQuotes: true, theme: "auto" };

  function loadPrefs() {
    try { return Object.assign({}, defaults, JSON.parse(localStorage.getItem(PREFS_KEY) || "{}")); }
    catch (e) { return Object.assign({}, defaults); }
  }
  function savePrefs(p) {
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch (e) { /* storage unavailable */ }
  }

  const isNativeShell = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
  const servedByBackend = location.protocol.startsWith("http") && !isNativeShell;

  function base() {
    const p = loadPrefs();
    const b = (p.apiBase || "").trim().replace(/\/+$/, "");
    if (b) return b;
    return servedByBackend ? "" : null;
  }

  class ApiError extends Error {
    constructor(status, code, message) { super(message); this.status = status; this.code = code; }
  }

  async function get(path, params) {
    const b = base();
    if (b === null) throw new ApiError(0, "no_api_base", "Set the server address in Settings.");
    const qs = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "")) : "";
    return request(b + path + qs, { headers: { Accept: "application/json" } });
  }

  async function put(path, body) {
    const b = base();
    if (b === null) throw new ApiError(0, "no_api_base", "Set the server address in Settings.");
    return request(b + path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  async function request(url, opts) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 120000);
    let res;
    try { res = await fetch(url, Object.assign({ signal: ctrl.signal }, opts)); }
    catch (e) { throw new ApiError(0, "network_error", e.name === "AbortError" ? "Request timed out." : "Cannot reach the server. Check that it is running and the address in Settings."); }
    finally { clearTimeout(timer); }
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok) {
      const err = (data && data.error) || {};
      throw new ApiError(res.status, err.code || "http_" + res.status, err.message || ("Server returned " + res.status));
    }
    return data;
  }

  function wsUrl(path) {
    const b = base();
    if (b === null) return null;
    if (b === "") return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + path;
    return b.replace(/^http/, "ws") + path;
  }

  class QuoteStream {
    constructor(onQuotes, onState) { this.onQuotes = onQuotes; this.onState = onState; this.ws = null; this.delay = 1000; this.stopped = true; this.symbols = []; }
    start(symbols, interval) {
      this.symbols = symbols; this.interval = interval || 5; this.stopped = false; this.delay = 1000; this._open();
    }
    stop() { this.stopped = true; clearTimeout(this.timer); if (this.ws) { try { this.ws.close(); } catch (e) { /* ignore */ } } this.ws = null; this.onState("off"); }
    _open() {
      if (this.stopped) return;
      const url = wsUrl("/ws/quotes?symbols=" + encodeURIComponent(this.symbols.join(",")) + "&interval=" + this.interval);
      if (!url) { this.onState("off"); return; }
      let ws;
      try { ws = new WebSocket(url); } catch (e) { this._retry(); return; }
      this.ws = ws;
      ws.onopen = () => { this.delay = 1000; this.onState("on"); };
      ws.onmessage = (ev) => {
        let msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
        if (msg.type === "quotes") this.onQuotes(msg.quotes, msg.time);
        else if (msg.type === "error") this.onState("error", msg.message);
      };
      ws.onclose = () => { if (!this.stopped) { this.onState("reconnecting"); this._retry(); } };
      ws.onerror = () => { try { ws.close(); } catch (e) { /* ignore */ } };
    }
    _retry() { clearTimeout(this.timer); this.timer = setTimeout(() => this._open(), this.delay); this.delay = Math.min(30000, this.delay * 2); }
  }

  window.SwingAPI = { get, put, ApiError, QuoteStream, loadPrefs, savePrefs, base, isNativeShell };
})();
