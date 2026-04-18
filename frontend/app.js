const API = "";
const charts = {};

// ── Helpers ──────────────────────────────────────────────────────────────────

function peClass(pe) {
  if (pe === null || pe === undefined) return "pe-muted";
  if (pe < 15)  return "pe-green";
  if (pe <= 30) return "pe-yellow";
  return "pe-red";
}

function fmt(val, decimals = 2) {
  if (val === null || val === undefined) return "—";
  return Number(val).toFixed(decimals);
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ── Market status badge ───────────────────────────────────────────────────────

function updateMarketBadge(isOpen) {
  const badge = document.getElementById("market-status");
  badge.textContent = isOpen ? "Market Open" : "Market Closed";
  badge.className = "market-badge " + (isOpen ? "open" : "closed");
}

// ── Chart ─────────────────────────────────────────────────────────────────────

function renderChart(ticker, history) {
  const canvasId = `chart-${ticker}`;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  if (charts[ticker]) {
    charts[ticker].destroy();
    delete charts[ticker];
  }

  if (!history || history.length === 0) return;

  const labels = history.map(r => r.date.slice(5));
  const values = history.map(r => r.trailing_pe);
  const spikes = history.map(r => r.is_spike);

  const pointColors = values.map((v, i) =>
    spikes[i] ? "#ef4444" : "rgba(99,102,241,0.8)"
  );
  const pointRadius = values.map((v, i) => spikes[i] ? 5 : 2);

  charts[ticker] = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: "#6366f1",
        borderWidth: 1.5,
        pointBackgroundColor: pointColors,
        pointRadius,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: false,
        spanGaps: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false }, tooltip: {
        callbacks: {
          label: ctx => `P/E: ${ctx.parsed.y !== null ? ctx.parsed.y.toFixed(1) : "—"}`,
        },
      }},
      scales: {
        x: { display: false },
        y: {
          display: true,
          grid: { color: "rgba(46,51,80,.5)" },
          ticks: { color: "#7a7f9a", font: { size: 10 }, maxTicksLimit: 4 },
        },
      },
    },
  });
}

// ── Card builder ─────────────────────────────────────────────────────────────

function buildCard(stock, historyMap) {
  const { ticker, company, live, market_open } = stock;
  const price    = live?.price;
  const trailingPE = live?.trailing_pe;
  const forwardPE  = live?.forward_pe;
  const history  = historyMap[ticker] || [];

  const card = document.createElement("div");
  card.className = "stock-card";
  card.dataset.ticker = ticker;

  card.innerHTML = `
    <div class="card-top">
      <div class="card-meta">
        <h3>${ticker}</h3>
        <div class="company" title="${company}">${company}</div>
      </div>
      <div class="card-stats">
        <div class="stat">
          <span class="stat-label">Price</span>
          <span class="stat-value">$${fmt(price)}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Trail P/E</span>
          <span class="stat-value ${peClass(trailingPE)}">${fmt(trailingPE, 1)}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Fwd P/E</span>
          <span class="stat-value ${peClass(forwardPE)}">${fmt(forwardPE, 1)}</span>
        </div>
      </div>
    </div>
    <div class="card-chart">
      <canvas id="chart-${ticker}"></canvas>
    </div>
    <div class="card-footer">
      <button class="btn btn-danger remove-btn" data-ticker="${ticker}">Remove</button>
    </div>
    ${!market_open ? '<div style="font-size:11px;color:#7a7f9a;text-align:right;">Market closed — last known values</div>' : ''}
  `;

  card.querySelector(".remove-btn").addEventListener("click", () => removeStock(ticker));

  return { card, ticker, history };
}

// ── Dashboard render ──────────────────────────────────────────────────────────

async function loadDashboard() {
  const sectorsEl = document.getElementById("sectors");
  const loadingEl = document.getElementById("loading");
  const emptyEl   = document.getElementById("empty");

  loadingEl.classList.remove("hidden");
  sectorsEl.innerHTML = "";
  emptyEl.classList.add("hidden");

  let grouped;
  try {
    grouped = await apiFetch("/stocks");
  } catch (e) {
    loadingEl.textContent = "Failed to load: " + e.message;
    return;
  }
  loadingEl.classList.add("hidden");

  const sectors = Object.keys(grouped);
  if (sectors.length === 0) {
    emptyEl.classList.remove("hidden");
    return;
  }

  // Fetch history for all tickers in parallel
  const allTickers = sectors.flatMap(s => grouped[s].map(st => st.ticker));
  const marketOpen = sectors.length > 0 && grouped[sectors[0]][0]?.market_open;
  updateMarketBadge(marketOpen ?? false);

  const historyMap = {};
  await Promise.all(allTickers.map(async ticker => {
    try {
      const data = await apiFetch(`/stocks/${ticker}/history`);
      historyMap[ticker] = data.history;
    } catch { historyMap[ticker] = []; }
  }));

  for (const sector of sectors.sort()) {
    const stocks = grouped[sector];
    const groupEl = document.createElement("div");
    groupEl.className = "sector-group";
    groupEl.innerHTML = `
      <div class="sector-header">
        <span class="sector-toggle">&#9660;</span>
        <h2>${sector}</h2>
        <div class="sector-divider"></div>
      </div>
      <div class="sector-cards"></div>
    `;

    const cardsEl = groupEl.querySelector(".sector-cards");
    const header  = groupEl.querySelector(".sector-header");
    const toggle  = groupEl.querySelector(".sector-toggle");

    header.addEventListener("click", () => {
      const collapsed = cardsEl.style.display === "none";
      cardsEl.style.display = collapsed ? "" : "none";
      toggle.classList.toggle("collapsed", !collapsed);
    });

    const cardPairs = stocks.map(stock => buildCard(stock, historyMap));
    for (const { card } of cardPairs) cardsEl.appendChild(card);

    sectorsEl.appendChild(groupEl);

    // Render charts after DOM is attached
    for (const { ticker, history } of cardPairs) {
      renderChart(ticker, history);
    }
  }
}

// ── Add stock ─────────────────────────────────────────────────────────────────

function openModal() {
  document.getElementById("modal-overlay").classList.remove("hidden");
  document.getElementById("ticker-input").value = "";
  document.getElementById("modal-error").classList.add("hidden");
  document.getElementById("ticker-input").focus();
}

function closeModal() {
  document.getElementById("modal-overlay").classList.add("hidden");
}

async function submitAddStock() {
  const input = document.getElementById("ticker-input");
  const errorEl = document.getElementById("modal-error");
  const submitBtn = document.getElementById("modal-submit");
  const ticker = input.value.trim().toUpperCase();

  if (!ticker) return;

  errorEl.classList.add("hidden");
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner"></span> Adding…';

  try {
    await apiFetch("/stocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker }),
    });
    closeModal();
    await loadDashboard();
  } catch (e) {
    errorEl.textContent = e.message;
    errorEl.classList.remove("hidden");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Add";
  }
}

async function removeStock(ticker) {
  if (!confirm(`Remove ${ticker} from your watchlist?`)) return;
  try {
    await apiFetch(`/stocks/${ticker}`, { method: "DELETE" });
    await loadDashboard();
  } catch (e) {
    alert("Error removing stock: " + e.message);
  }
}

// ── Refresh ───────────────────────────────────────────────────────────────────

async function manualRefresh() {
  const btn = document.getElementById("refresh-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    await apiFetch("/refresh", { method: "POST" });
    await loadDashboard();
  } catch (e) {
    alert("Refresh failed: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh";
  }
}

// ── Event wiring ──────────────────────────────────────────────────────────────

document.getElementById("add-btn").addEventListener("click", openModal);
document.getElementById("modal-cancel").addEventListener("click", closeModal);
document.getElementById("modal-submit").addEventListener("click", submitAddStock);
document.getElementById("refresh-btn").addEventListener("click", manualRefresh);

document.getElementById("modal-overlay").addEventListener("click", e => {
  if (e.target === e.currentTarget) closeModal();
});

document.getElementById("ticker-input").addEventListener("keydown", e => {
  if (e.key === "Enter") submitAddStock();
  if (e.key === "Escape") closeModal();
});

// ── Boot ──────────────────────────────────────────────────────────────────────

loadDashboard();
