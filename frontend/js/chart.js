/* Dependency-free canvas candlestick chart with volume and SMA overlays. */
(function () {
  const OVERLAY_COLORS = { sma20: "#4c9aff", sma50: "#e5b33b", sma200: "#a371f7" };

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function fmtTs(iso, tf) {
    const d = new Date(iso);
    const opts = tf === "1d" ? { day: "2-digit", month: "short", year: "2-digit" } : { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" };
    return d.toLocaleString("en-IN", Object.assign({ timeZone: "Asia/Kolkata" }, opts));
  }

  class CandleChart {
    constructor(box) {
      this.box = box;
      this.canvas = document.createElement("canvas");
      this.tip = document.createElement("div");
      this.tip.className = "chart-tip";
      box.appendChild(this.canvas);
      box.appendChild(this.tip);
      this.data = null;
      this.hover = null;
      this.ro = new ResizeObserver(() => this.draw());
      this.ro.observe(box);
      const move = (x) => {
        if (!this.data) return;
        const i = Math.floor((x - this.left) / this.step);
        this.hover = i >= 0 && i < this.data.candles.length ? i : null;
        this.draw();
      };
      this.canvas.addEventListener("mousemove", (e) => move(e.offsetX));
      this.canvas.addEventListener("mouseleave", () => { this.hover = null; this.draw(); });
      this.canvas.addEventListener("touchstart", (e) => { const r = this.canvas.getBoundingClientRect(); move(e.touches[0].clientX - r.left); }, { passive: true });
      this.canvas.addEventListener("touchmove", (e) => { const r = this.canvas.getBoundingClientRect(); move(e.touches[0].clientX - r.left); }, { passive: true });
    }

    setData(data) { this.data = data; this.hover = null; this.draw(); }
    destroy() { this.ro.disconnect(); }

    draw() {
      const d = this.data;
      const w = this.box.clientWidth, h = this.box.clientHeight;
      if (!w || !h) return;
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = w * dpr; this.canvas.height = h * dpr;
      const ctx = this.canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      if (!d || !d.candles.length) {
        ctx.fillStyle = css("--muted"); ctx.font = "13px system-ui"; ctx.fillText("No chart data", 12, 24); return;
      }
      const c = d.candles, n = c.length;
      const axisW = 64, padTop = 22, volH = Math.round(h * 0.18), padBottom = 18;
      this.left = 4; const right = w - axisW;
      this.step = (right - this.left) / n;
      const priceH = h - padTop - volH - padBottom - 6;
      let hi = -Infinity, lo = Infinity, vmax = 0;
      for (let i = 0; i < n; i++) { hi = Math.max(hi, c[i].high); lo = Math.min(lo, c[i].low); vmax = Math.max(vmax, c[i].volume); }
      for (const k of Object.keys(d.overlays || {})) for (const v of d.overlays[k]) if (v != null) { hi = Math.max(hi, v); lo = Math.min(lo, v); }
      const pad = (hi - lo) * 0.05 || 1; hi += pad; lo -= pad;
      const y = (p) => padTop + (hi - p) / (hi - lo) * priceH;
      const grid = css("--border"), muted = css("--muted"), up = css("--buy"), dn = css("--sell");

      ctx.font = "11px ui-monospace, monospace"; ctx.textBaseline = "middle";
      for (let g = 0; g <= 4; g++) {
        const p = lo + (hi - lo) * g / 4, yy = y(p);
        ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(this.left, yy); ctx.lineTo(right, yy); ctx.stroke();
        ctx.fillStyle = muted; ctx.fillText(p.toFixed(p > 1000 ? 0 : 2), right + 6, yy);
      }
      const bw = Math.max(1, this.step * 0.7);
      const volTop = h - padBottom - volH;
      for (let i = 0; i < n; i++) {
        const k = c[i], x = this.left + i * this.step + this.step / 2, col = k.close >= k.open ? up : dn;
        ctx.strokeStyle = col; ctx.fillStyle = col;
        ctx.beginPath(); ctx.moveTo(x, y(k.high)); ctx.lineTo(x, y(k.low)); ctx.stroke();
        const top = y(Math.max(k.open, k.close)), bh = Math.max(1, Math.abs(y(k.open) - y(k.close)));
        ctx.fillRect(x - bw / 2, top, bw, bh);
        if (vmax > 0) { ctx.globalAlpha = 0.35; const vh = k.volume / vmax * volH; ctx.fillRect(x - bw / 2, volTop + volH - vh, bw, vh); ctx.globalAlpha = 1; }
      }
      for (const [k, arr] of Object.entries(d.overlays || {})) {
        ctx.strokeStyle = OVERLAY_COLORS[k] || muted; ctx.lineWidth = 1.5; ctx.beginPath();
        let started = false;
        arr.forEach((v, i) => { if (v == null) { started = false; return; } const x = this.left + i * this.step + this.step / 2; if (!started) { ctx.moveTo(x, y(v)); started = true; } else ctx.lineTo(x, y(v)); });
        ctx.stroke();
      }
      const lastClose = c[n - 1].close, ly = y(lastClose);
      ctx.setLineDash([4, 4]); ctx.strokeStyle = muted; ctx.beginPath(); ctx.moveTo(this.left, ly); ctx.lineTo(right, ly); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = css("--accent"); ctx.fillRect(right + 2, ly - 9, axisW - 4, 18);
      ctx.fillStyle = "#fff"; ctx.fillText(lastClose.toFixed(2), right + 6, ly);
      ctx.fillStyle = muted; ctx.textBaseline = "alphabetic";
      ctx.fillText(fmtTs(c[0].ts, d.timeframe), this.left + 2, h - 4);
      const endLabel = fmtTs(c[n - 1].ts, d.timeframe); ctx.fillText(endLabel, right - ctx.measureText(endLabel).width - 4, h - 4);

      const i = this.hover != null ? this.hover : n - 1, k = c[i];
      if (this.hover != null) {
        const x = this.left + i * this.step + this.step / 2;
        ctx.strokeStyle = muted; ctx.globalAlpha = 0.6; ctx.beginPath(); ctx.moveTo(x, padTop); ctx.lineTo(x, h - padBottom); ctx.stroke(); ctx.globalAlpha = 1;
      }
      this.tip.textContent = `${fmtTs(k.ts, d.timeframe)}  O ${k.open.toFixed(2)}  H ${k.high.toFixed(2)}  L ${k.low.toFixed(2)}  C ${k.close.toFixed(2)}  V ${Math.round(k.volume).toLocaleString("en-IN")}`;
    }
  }

  window.CandleChart = CandleChart;
  window.CHART_COLORS = OVERLAY_COLORS;
})();
