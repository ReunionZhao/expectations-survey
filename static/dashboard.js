// ============================================================
// Probabilistic Judgement dashboard
// ============================================================

const POLL_MS = 3000;

const STEVE_OCCUPATIONS = ["Farmer", "Salesman", "Airline Pilot", "Librarian", "Physician"];

const LETTER_K_LABELS = ["availability_heuristic", "systematic_estimation", "pure_guess", "other"];
const STEVE_LABELS = ["representativeness", "base_rate", "mixed", "other"];
const TAXI_LABELS = ["witness_accuracy_anchor", "bayesian", "base_rate_anchor", "mixed_or_other"];

// SBS palette (matches original Gamble template)
const COLORS = {
  arm_a: "#007f78",
  arm_b: "#00a651",
  steve: "#00a6a6",
};

Chart.defaults.font.family = 'Cambria, "Times New Roman", Times, serif';
Chart.defaults.font.size = 14;
Chart.defaults.color = "#0a113f";

// ------------------------------------------------------------
// Custom plugin: draw vertical reference lines on a histogram
// Lines are configured via chart.options.plugins.refLines.lines.
// Each line: { value: 0-100, label: string, color: css color }.
// ------------------------------------------------------------
const refLinesPlugin = {
  id: "refLinesPlugin",
  afterDatasetsDraw(chart) {
    const cfg = chart.options.plugins?.refLines;
    if (!cfg || !cfg.lines || !cfg.lines.length) return;
    const xScale = chart.scales.x;
    if (!xScale) return;
    const area = chart.chartArea;
    const ctx = chart.ctx;
    const px0 = xScale.getPixelForValue(0);
    const px1 = xScale.getPixelForValue(1);
    const barWidth = px1 - px0;
    cfg.lines.forEach((line) => {
      const x = px0 + (line.value / 10 - 0.5) * barWidth;
      ctx.save();
      ctx.strokeStyle = line.color || "#000";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(x, area.top);
      ctx.lineTo(x, area.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = line.color || "#000";
      ctx.font = "bold 12px Cambria, serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(line.label, x, area.top - 2);
      ctx.restore();
    });
  },
};
Chart.register(refLinesPlugin);

const TAXI_REF_LINES = [
  { value: 25, label: "25% Base rate", color: "#6e2436" },
  { value: 57, label: "57% Bayesian", color: "#0a113f" },
  { value: 80, label: "80% Likelihood", color: "#a85a00" },
];

// ------------------------------------------------------------
// Histogram binning helper: 10 percent wide bins, 10 bars per chart
// X labels at the bin lower bound: "0", "10", ..., "90"
// ------------------------------------------------------------
const BIN_WIDTH = 10;
const HIST_BINS = Array.from({ length: 100 / BIN_WIDTH }, (_, i) => i * BIN_WIDTH);
const HIST_LABELS = HIST_BINS.map((lo) => String(lo));

function binCounts(values) {
  const counts = HIST_BINS.map(() => 0);
  values.forEach((v) => {
    if (typeof v !== "number" || isNaN(v)) return;
    let idx = Math.floor(v / BIN_WIDTH);
    if (idx >= counts.length) idx = counts.length - 1;
    if (idx < 0) idx = 0;
    counts[idx] += 1;
  });
  return counts;
}

function asPercent(counts, total) {
  if (!total) return counts.map(() => 0);
  return counts.map((c) => Number(((c / total) * 100).toFixed(1)));
}

function wrapLabel(s) {
  return String(s || "").split("_");
}

function fmtLabelInline(s) {
  return String(s || "").replace(/_/g, " ");
}

// ------------------------------------------------------------
// Chart factories
// ------------------------------------------------------------
const PERCENT_Y_AXIS = {
  beginAtZero: true,
  max: 100,
  ticks: {
    stepSize: 20,
    callback: (v) => `${v}%`,
  },
};

function makeHistogram(canvasId, color, refLines) {
  const ctx = document.getElementById(canvasId);
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels: HIST_LABELS,
      datasets: [{
        label: "% of respondents",
        data: HIST_BINS.map(() => 0),
        backgroundColor: color,
        barPercentage: 1.0,
        categoryPercentage: 1.0,
      }],
    },
    options: {
      responsive: true,
      layout: { padding: { top: refLines && refLines.length ? 22 : 4 } },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `${ctx.parsed.y}%` } },
        refLines: { lines: refLines || [] },
      },
      scales: {
        x: {
          title: { display: true, text: "percent guessed (%)" },
          ticks: { maxRotation: 0, minRotation: 0, autoSkip: false },
        },
        y: PERCENT_Y_AXIS,
      },
    },
  });
}

function makeGroupedCategoryBar(canvasId, categories, datasetsConfig) {
  const ctx = document.getElementById(canvasId);
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels: categories.map(wrapLabel),
      datasets: datasetsConfig.map((d) => ({
        label: d.label,
        data: categories.map(() => 0),
        backgroundColor: d.color,
      })),
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: true, position: "top", labels: { font: { size: 15 } } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}%` } },
      },
      scales: {
        x: {
          ticks: {
            autoSkip: false,
            maxRotation: 0,
            minRotation: 0,
            font: { size: 16 },
          },
        },
        y: PERCENT_Y_AXIS,
      },
    },
  });
}

function makeSingleCategoryBar(canvasId, categories, color) {
  const ctx = document.getElementById(canvasId);
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels: categories.map(wrapLabel),
      datasets: [{ label: "% of respondents", data: categories.map(() => 0), backgroundColor: color }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `${ctx.parsed.y}%` } },
      },
      scales: {
        x: {
          ticks: {
            autoSkip: false,
            maxRotation: 0,
            minRotation: 0,
            font: { size: 16 },
          },
        },
        y: PERCENT_Y_AXIS,
      },
    },
  });
}

// ------------------------------------------------------------
// Charts (created once, updated on each refresh)
// ------------------------------------------------------------
let kHistFirstChart, kHistThirdChart, kLabelsChart;
let steveLabelsChart, steveFirstChart, steveSecondChart;
let taxiHistProbChart, taxiHistFreqChart, taxiLabelsChart;

function initCharts() {
  kHistFirstChart = makeHistogram("kHistFirst", COLORS.arm_a);
  kHistThirdChart = makeHistogram("kHistThird", COLORS.arm_b);
  kLabelsChart = makeGroupedCategoryBar(
    "kLabels",
    LETTER_K_LABELS.concat(["unclassified"]),
    [
      { label: "Arm: first", color: COLORS.arm_a },
      { label: "Arm: third", color: COLORS.arm_b },
    ]
  );

  steveLabelsChart = makeSingleCategoryBar("steveLabels", STEVE_LABELS.concat(["unclassified"]), COLORS.steve);
  steveFirstChart = makeSingleCategoryBar("steveFirst", STEVE_OCCUPATIONS, COLORS.arm_a);
  steveSecondChart = makeSingleCategoryBar("steveSecond", STEVE_OCCUPATIONS, COLORS.arm_b);

  taxiHistProbChart = makeHistogram("taxiHistProb", COLORS.arm_a, TAXI_REF_LINES);
  taxiHistFreqChart = makeHistogram("taxiHistFreq", COLORS.arm_b, TAXI_REF_LINES);
  taxiLabelsChart = makeGroupedCategoryBar(
    "taxiLabels",
    TAXI_LABELS.concat(["unclassified"]),
    [
      { label: "Arm: probability", color: COLORS.arm_a },
      { label: "Arm: frequentist", color: COLORS.arm_b },
    ]
  );
}

// ------------------------------------------------------------
// Steve heatmap (colored cells + percentage of total)
// ------------------------------------------------------------
function renderSteveHeatmap(matrix, total) {
  const wrap = document.getElementById("steveHeatmapWrap");
  let maxVal = 0;
  STEVE_OCCUPATIONS.forEach((r) =>
    STEVE_OCCUPATIONS.forEach((c) => {
      const v = matrix[r]?.[c] ?? 0;
      if (v > maxVal) maxVal = v;
    })
  );

  const table = document.createElement("table");
  table.className = "heatmap-table";
  const thead = document.createElement("thead");
  let head = "<tr><th></th>";
  STEVE_OCCUPATIONS.forEach((c) => (head += `<th>${c}</th>`));
  head += "</tr>";
  thead.innerHTML = head;
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  STEVE_OCCUPATIONS.forEach((r) => {
    const tr = document.createElement("tr");
    let row = `<th>${r}</th>`;
    STEVE_OCCUPATIONS.forEach((c) => {
      const v = matrix[r]?.[c] ?? 0;
      const intensity = maxVal > 0 ? v / maxVal : 0;
      const bg = `rgba(0,127,120,${intensity.toFixed(2)})`;
      const fg = intensity > 0.55 ? "#ffffff" : "#0a113f";
      const pct = total > 0 ? ((v / total) * 100).toFixed(0) : 0;
      const display = total > 0 ? `${pct}%` : "0%";
      row += `<td class="cell" style="background:${bg};color:${fg}">${display}</td>`;
    });
    tr.innerHTML = row;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.innerHTML = "";
  wrap.appendChild(table);
}

// ------------------------------------------------------------
// Raw data: groups of <details> per arm (collapsible)
// ------------------------------------------------------------
function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function buildTable(rows, columns) {
  if (!rows.length) {
    return '<p class="tiny" style="padding: 10px 12px;">No responses in this group yet.</p>';
  }
  const head = "<thead><tr>" + columns.map((c) => `<th>${c.label}</th>`).join("") + "</tr></thead>";
  const body =
    "<tbody>" +
    rows.map((r) =>
      "<tr>" +
      columns.map((c) => {
        const v = c.get(r);
        return `<td>${v === null || v === undefined ? "" : escapeHtml(v)}</td>`;
      }).join("") +
      "</tr>"
    ).join("") +
    "</tbody>";
  return `<table>${head}${body}</table>`;
}

function renderRawDataGroups(containerId, groups, columns) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  groups.forEach((g) => {
    const details = document.createElement("details");
    details.className = "response-group";
    const summary = document.createElement("summary");
    summary.textContent = `${g.label} (${g.rows.length})`;
    details.appendChild(summary);
    const wrap = document.createElement("div");
    wrap.innerHTML = buildTable(g.rows, columns);
    details.appendChild(wrap);
    container.appendChild(details);
  });
}

// ------------------------------------------------------------
// Word cloud refresh (cache buster)
// ------------------------------------------------------------
function refreshWordClouds() {
  const t = Date.now();
  const swap = (id, url) => {
    const img = document.getElementById(id);
    if (img) img.src = `${url}?t=${t}`;
  };
  swap("kWcFirst", "/api/wordcloud_image/letter_k/first");
  swap("kWcThird", "/api/wordcloud_image/letter_k/third");
  swap("steveWc", "/api/wordcloud_image/steve/all");
  swap("taxiWcProb", "/api/wordcloud_image/taxi/probability");
  swap("taxiWcFreq", "/api/wordcloud_image/taxi/frequentist");
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

// ------------------------------------------------------------
// Main refresh
// ------------------------------------------------------------
async function refreshData() {
  let data;
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) throw new Error("stats fetch failed");
    data = await res.json();
  } catch (e) {
    return;
  }

  // ---- Letter K ----
  const k = data.letter_k;
  const kFirstN = k.by_arm.first.length;
  const kThirdN = k.by_arm.third.length;
  setText("kCountFirst", kFirstN);
  setText("kCountThird", kThirdN);

  kHistFirstChart.data.datasets[0].data = asPercent(binCounts(k.by_arm.first), kFirstN);
  kHistFirstChart.update();
  kHistThirdChart.data.datasets[0].data = asPercent(binCounts(k.by_arm.third), kThirdN);
  kHistThirdChart.update();

  const kCats = LETTER_K_LABELS.concat(["unclassified"]);
  const kFirstCounts = kCats.map((c) =>
    c === "unclassified" ? k.label_unclassified_by_arm.first : (k.label_counts_by_arm.first[c] || 0)
  );
  const kThirdCounts = kCats.map((c) =>
    c === "unclassified" ? k.label_unclassified_by_arm.third : (k.label_counts_by_arm.third[c] || 0)
  );
  kLabelsChart.data.datasets[0].data = asPercent(kFirstCounts, kFirstN);
  kLabelsChart.data.datasets[1].data = asPercent(kThirdCounts, kThirdN);
  kLabelsChart.update();

  const kColumns = [
    { label: "%", get: (r) => (r.numeric === null ? "" : r.numeric) },
    { label: "Reasoning", get: (r) => r.text },
    { label: "Label", get: (r) => fmtLabelInline(r.label) },
  ];
  const kFirstRows = k.latest.filter((r) => r.arm === "first");
  const kThirdRows = k.latest.filter((r) => r.arm === "third");
  renderRawDataGroups("kLatest", [
    { label: "Arm: first", rows: kFirstRows },
    { label: "Arm: third", rows: kThirdRows },
  ], kColumns);

  // ---- Steve ----
  const s = data.steve;
  setText("steveTotalLocal", s.total);
  const sTotal = s.total;

  steveFirstChart.data.datasets[0].data = asPercent(
    STEVE_OCCUPATIONS.map((o) => s.first_counts[o] || 0),
    sTotal
  );
  steveFirstChart.update();
  steveSecondChart.data.datasets[0].data = asPercent(
    STEVE_OCCUPATIONS.map((o) => s.second_counts[o] || 0),
    sTotal
  );
  steveSecondChart.update();

  const sCounts = STEVE_LABELS.map((l) => s.label_counts[l] || 0);
  sCounts.push(s.label_unclassified || 0);
  steveLabelsChart.data.datasets[0].data = asPercent(sCounts, sTotal);
  steveLabelsChart.update();

  renderSteveHeatmap(s.first_to_second, sTotal);

  renderRawDataGroups("steveLatest", [
    { label: "All responses", rows: s.latest },
  ], [
    { label: "Most likely", get: (r) => r.choice_1 },
    { label: "Second", get: (r) => r.choice_2 },
    { label: "Reasoning", get: (r) => r.text },
    { label: "Label", get: (r) => fmtLabelInline(r.label) },
  ]);

  // ---- Taxi ----
  const t = data.taxi;
  const tProbN = t.by_arm.probability.length;
  const tFreqN = t.by_arm.frequentist.length;
  setText("taxiCountProb", tProbN);
  setText("taxiCountFreq", tFreqN);

  taxiHistProbChart.data.datasets[0].data = asPercent(binCounts(t.by_arm.probability), tProbN);
  taxiHistProbChart.update();
  taxiHistFreqChart.data.datasets[0].data = asPercent(binCounts(t.by_arm.frequentist), tFreqN);
  taxiHistFreqChart.update();

  const tCats = TAXI_LABELS.concat(["unclassified"]);
  const tProbCounts = tCats.map((c) =>
    c === "unclassified" ? t.label_unclassified_by_arm.probability : (t.label_counts_by_arm.probability[c] || 0)
  );
  const tFreqCounts = tCats.map((c) =>
    c === "unclassified" ? t.label_unclassified_by_arm.frequentist : (t.label_counts_by_arm.frequentist[c] || 0)
  );
  taxiLabelsChart.data.datasets[0].data = asPercent(tProbCounts, tProbN);
  taxiLabelsChart.data.datasets[1].data = asPercent(tFreqCounts, tFreqN);
  taxiLabelsChart.update();

  const taxiColumns = [
    { label: "%", get: (r) => (r.numeric === null ? "" : r.numeric) },
    { label: "Reasoning", get: (r) => r.text },
    { label: "Label", get: (r) => fmtLabelInline(r.label) },
  ];
  const taxiProbRows = t.latest.filter((r) => r.arm === "probability");
  const taxiFreqRows = t.latest.filter((r) => r.arm === "frequentist");
  renderRawDataGroups("taxiLatest", [
    { label: "Arm: probability", rows: taxiProbRows },
    { label: "Arm: frequentist", rows: taxiFreqRows },
  ], taxiColumns);

  refreshWordClouds();
}

// ------------------------------------------------------------
// Per-module button handlers
// ------------------------------------------------------------
const statusText = document.getElementById("statusText");

function setStatus(msg) {
  if (statusText) statusText.textContent = msg;
}

async function manualRefresh() {
  setStatus("Refreshing...");
  await refreshData();
  setStatus("Refreshed.");
}

async function reanalyzeModule(module) {
  setStatus(`Queuing analysis for unlabeled ${module} responses...`);
  try {
    const res = await fetch(`/api/analyze_pending/${module}`, { method: "POST" });
    const data = await res.json();
    setStatus(`Queued ${data.queued} ${module} item(s). Labels will appear in a few seconds.`);
  } catch (e) {
    setStatus("Analysis request failed.");
  }
}

async function resetModule(module) {
  if (!window.confirm(`Delete all responses for module "${module}"?`)) return;
  await fetch(`/api/reset_module/${module}`, { method: "POST" });
  setStatus(`Module ${module} reset.`);
  refreshData();
}

async function showPrompt(module) {
  const res = await fetch("/api/prompts");
  const data = await res.json();
  const titles = { letter_k: "Letter K prompt", steve: "Steve prompt", taxi: "Taxi Cab prompt" };
  document.getElementById("promptTitle").textContent = titles[module] || "Prompt";
  document.getElementById("promptContent").textContent = data[module] || "";
  document.getElementById("promptModal").classList.remove("hidden");
}

function closePrompt() {
  document.getElementById("promptModal").classList.add("hidden");
}

// ------------------------------------------------------------
// Bootstrap
// ------------------------------------------------------------
document.querySelectorAll("[data-action]").forEach((btn) => {
  const action = btn.dataset.action;
  const module = btn.dataset.module;
  btn.addEventListener("click", () => {
    if (action === "refresh") manualRefresh();
    else if (action === "reanalyze") reanalyzeModule(module);
    else if (action === "reset") resetModule(module);
    else if (action === "prompt") showPrompt(module);
  });
});
document.getElementById("closePromptBtn").addEventListener("click", closePrompt);
document.getElementById("promptModal").addEventListener("click", (e) => {
  if (e.target.id === "promptModal") closePrompt();
});

initCharts();
refreshData();
setInterval(refreshData, POLL_MS);
