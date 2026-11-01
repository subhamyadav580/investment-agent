// Investment Agent UI: a thin client over the JSON API. No build step; every value from the API is escaped.

const view = document.getElementById("view");
const KEY_STORE = "investment-agent.api-key";

const LABELS = {
  strong_candidate: "Strong candidate",
  good_business_expensive: "Good business, expensive valuation",
  potential_opportunity: "Potential opportunity",
  high_risk: "High risk",
  insufficient_evidence: "Insufficient evidence",
};
const CLASS_TONE = {
  strong_candidate: "good", good_business_expensive: "warn", potential_opportunity: "info",
  high_risk: "bad", insufficient_evidence: "",
};
const LABEL_TONE = Object.fromEntries(Object.entries(LABELS).map(([k, v]) => [v, CLASS_TONE[k]]));
const RATING_TONE = {
  Strong: "good", Positive: "good", Attractive: "good", High: "good", Improving: "good", Present: "good",
  Average: "info", Fair: "info", Mixed: "warn", Medium: "warn", Stable: "info",
  Weak: "bad", Concerning: "bad", Expensive: "warn", Low: "bad", Weakening: "bad",
};
const STATUS_TONE = {
  complete: "good", partial: "warn", insufficient_data: "bad", candidate: "good", rejected: "bad",
  ineligible: "", governance_review: "warn", excluded_instrument: "", completed: "good", failed: "bad",
  running: "info", pass: "good", fail: "bad", missing: "warn", flag: "warn", not_applicable: "",
  delivered: "good", pending: "warn", suppressed: "", critical: "bad", warning: "warn", info: "info",
  serious: "bad", high: "bad", medium: "warn", low: "info",
};
const ASSESSMENT_ROWS = [
  ["business_quality", "Business quality"], ["financial_health", "Financial health"],
  ["management_governance", "Management and governance"], ["valuation", "Valuation"],
  ["data_quality", "Data quality"],
];
const METRIC_NAMES = {
  pe: "P/E", pb: "P/B", ev_ebitda: "EV/EBITDA", market_cap_cr: "Market cap", last_price: "Last price",
  roce_latest: "ROCE", roce_avg_3y: "ROCE (3y avg)", roe_latest: "ROE", roe_avg_3y: "ROE (3y avg)",
  roa_latest: "ROA", cfo_to_pat_3y: "Cash flow / profit (3y)", net_debt_to_ebitda: "Net debt / EBITDA",
  revenue_cagr: "Revenue CAGR", profit_cagr: "Profit CAGR", revenue_cagr_long: "Revenue CAGR (long)",
  profit_cagr_long: "Profit CAGR (long)", gross_npa_pct: "Gross NPA", net_npa_pct: "Net NPA",
  revenue_growth_q_yoy: "Revenue growth (quarter YoY)", profit_growth_q_yoy: "Profit growth (quarter YoY)",
  profit_growth_q_yoy_prev: "Profit growth (prev quarter YoY)", cfo: "Operating cash flow",
  return_on_incremental_capital: "Return on incremental capital",
};

// ---------- helpers ----------

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const titleCase = (s) => String(s).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const metricName = (k) => METRIC_NAMES[k] || titleCase(k);
const badge = (text, tone) => `<span class="badge ${tone ?? STATUS_TONE[text] ?? ""}">${esc(titleCase(text))}</span>`;
const ratingBadge = (r) => `<span class="badge ${RATING_TONE[r] || ""}">${esc(r ?? "–")}</span>`;
const classBadge = (cls, label) => `<span class="badge ${CLASS_TONE[cls] ?? ""}">${esc(label || LABELS[cls] || cls)}</span>`;
const labelBadge = (label) => (label ? `<span class="badge ${LABEL_TONE[label] ?? ""}">${esc(label)}</span>` : `<span class="muted">–</span>`);
const list = (items) => (items?.length ? `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : `<p class="muted">None.</p>`);
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);
const date = (d) => (d ? new Date(d).toLocaleString() : "–");

function num(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Number(v).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
const pct = (v, digits = 1) => (v === null || v === undefined ? "–" : `${num(v * 100, digits)}%`);
const signedPct = (v) => (v === null || v === undefined ? "–" : `${v >= 0 ? "+" : ""}${num(v * 100, 1)}%`);

function fmtMetric(m) {
  if (!m || m.value === null || m.value === undefined) return m?.note ? esc(m.note) : "–";
  switch (m.unit) {
    case "ratio": return pct(m.value);
    case "pct": return `${num(m.value, 2)}%`;
    case "pp": return `${m.value >= 0 ? "+" : ""}${num(m.value, 2)} pp`;
    case "x": return `${num(m.value, 2)}x`;
    case "INR_crore": return `₹${num(m.value, 0)} cr`;
    case "days": return `${num(m.value, 0)} days`;
    case "count": return num(m.value, 0);
    default: return num(m.value, 2);
  }
}

function getKey() {
  try { return localStorage.getItem(KEY_STORE) || ""; } catch { return ""; }
}
function setKey(k) {
  try { k ? localStorage.setItem(KEY_STORE, k) : localStorage.removeItem(KEY_STORE); } catch { /* storage blocked */ }
}

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body, params } = {}) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  const headers = { "X-API-Key": getKey() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = data?.detail ?? res.statusText;
    if (Array.isArray(msg)) msg = msg.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    throw new ApiError(res.status, String(msg));
  }
  return data;
}

function toast(msg, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = isError ? "error" : "";
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, isError ? 7000 : 3500);
}

function errorView(e) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 503)) {
    return `<div class="card"><h2>API key needed</h2><p>${esc(e.message)}.</p>
      <p><a href="#/settings">Set the API key</a> (the <span class="mono">API_KEY</span> value from your <span class="mono">.env</span>).</p></div>`;
  }
  return `<div class="card"><h2>Something went wrong</h2><p>${esc(e.message)}</p></div>`;
}

// Runs a button's action with a spinner, and reports failures without losing the page.
async function busy(button, label, fn) {
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span> ${esc(label)}`;
  try { return await fn(); } catch (e) { toast(e.message, true); } finally { button.disabled = false; button.innerHTML = original; }
}

function table(headers, rows, { empty = "Nothing here yet." } = {}) {
  if (!rows.length) return `<p class="empty">${esc(empty)}</p>`;
  const th = headers.map((h) => (typeof h === "string" ? `<th>${esc(h)}</th>` : `<th class="${h.cls || ""}">${esc(h.label)}</th>`)).join("");
  return `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

function kv(obj, digits = 2) {
  const entries = Object.entries(obj || {}).filter(([, v]) => v !== null && v !== undefined && typeof v !== "object");
  if (!entries.length) return `<p class="muted">Not available.</p>`;
  return `<div class="grid">${entries.map(([k, v]) => `<div class="stat"><div class="k">${esc(titleCase(k))}</div>
    <div class="v">${esc(typeof v === "number" ? num(v, digits) : v)}</div></div>`).join("")}</div>`;
}

function metricGrid(metrics) {
  const items = Object.values(metrics || {});
  if (!items.length) return `<p class="muted">Not available.</p>`;
  return `<div class="grid">${items.map((m) => `<div class="stat" title="${esc(JSON.stringify(m.inputs || {}))}">
    <div class="k">${esc(metricName(m.key))}</div><div class="v">${fmtMetric(m)}</div>
    <div class="p">${esc(m.period || "")}${m.note && m.value !== null ? ` · ${esc(m.note)}` : ""}</div></div>`).join("")}</div>`;
}

const evidenceLinks = (ids) => (ids || []).map((id) => `<a class="ev" href="#ev-${esc(id)}" data-ev="${esc(id)}">${esc(id)}</a>`).join(" ");

// ---------- views ----------

async function researchView() {
  view.innerHTML = `
    <h1>Research a company</h1>
    <form class="card" id="research-form">
      <div class="row">
        <label class="grow">Company name or NSE symbol (you can add a horizon in words)
          <input name="query" required maxlength="160" placeholder="e.g. Asian Paints for a 5-year investment" autofocus></label>
        <label>Horizon
          <select name="horizon">
            <option value="">From the text (default long term)</option>
            <option value="long_term">Long term (5–10 years)</option>
            <option value="medium_term">Medium term (1–3 years)</option>
            <option value="both">Both</option>
          </select></label>
        <label>Years
          <input name="years" type="number" min="1" max="10" style="width:80px" placeholder="auto"></label>
        <label>As of
          <input name="as_of_date" type="date"></label>
        <button class="primary" type="submit">Research</button>
      </div>
      <p class="small muted" style="margin-top:8px">Fetches filings, prices and financials, then scores the company.
        With the LLM enabled this makes 3 model calls and can take a minute or two.</p>
    </form>
    <div class="card"><h2>Recent reports</h2><div id="recent"><span class="spinner"></span></div></div>`;

  const form = document.getElementById("research-form");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const body = { query: f.get("query").trim() };
    if (f.get("horizon")) body.horizon = f.get("horizon");
    if (f.get("years")) body.years = Number(f.get("years"));
    if (f.get("as_of_date")) body.as_of_date = f.get("as_of_date");
    busy(form.querySelector("button"), "Researching…", async () => {
      const out = await api("/research", { method: "POST", body });
      location.hash = `#/reports/${out.id}`;
    });
  });

  try {
    const reports = await api("/research/reports", { params: { limit: 25 } });
    document.getElementById("recent").innerHTML = reportTable(reports);
  } catch (e) {
    document.getElementById("recent").innerHTML = errorView(e);
  }
}

function reportTable(reports) {
  return table(
    ["#", "Symbol", "As of", "Conclusion", "Status", "Created"],
    reports.map((r) => `<tr class="clickable" data-href="#/reports/${r.id}"><td>${r.id}</td><td><strong>${esc(r.symbol)}</strong></td>
      <td>${esc(r.as_of_date)}</td><td>${classBadge(r.conclusion)}</td><td>${badge(r.status)}</td>
      <td class="small muted">${esc(date(r.created_at))}</td></tr>`),
    { empty: "No reports yet. Research a company above." },
  );
}

async function reportView(id) {
  view.innerHTML = `<p><span class="spinner"></span> Loading report #${esc(id)}…</p>`;
  let out;
  try { out = await api(`/research/reports/${encodeURIComponent(id)}`); } catch (e) { view.innerHTML = errorView(e); return; }
  const d = out.report;
  const fa = d.final_assessment || {};
  const primary = d.horizon?.primary;
  const horizons = Object.entries(fa.horizons || {}).sort(([a], [b]) => (b === primary) - (a === primary)).map(([, h]) => h);
  const redFlags = d.risks?.red_flags || [];

  view.innerHTML = `
    <p class="small"><a href="#/research">← Research</a></p>
    <div class="card">
      <div class="row" style="align-items:flex-start">
        <div class="grow">
          <h1>${esc(d.name)} <span class="muted mono" style="font-size:16px">${esc(d.symbol)} · ${esc(d.exchange)}</span></h1>
          <p class="muted">${esc([d.sector, d.industry].filter(Boolean).join(" · ") || "Sector unknown")} · as of ${esc(d.as_of_date)}</p>
        </div>
        <div style="text-align:right">
          ${badge(d.research_status)}
          <p class="small muted" style="margin-top:6px">Report #${out.id} · rules ${esc(out.rules_version)} · prompts ${esc(out.prompt_version)}
            ${out.model_version ? ` · ${esc(out.model_version)}` : " · no LLM"}</p>
        </div>
      </div>
      <p>${esc(d.executive_summary)}</p>
    </div>

    <div class="grid-2">${horizons.map(horizonCard).join("")}</div>

    ${redFlags.length ? `<div class="alert-box"><h2>Red flags (${redFlags.length})</h2>
      ${table(["Flag", "Category", "Detail", "Evidence"], redFlags.map((f) => `<tr><td class="mono small">${esc(f.code)}</td>
        <td>${esc(titleCase(f.category || ""))}</td><td>${esc(f.message)}</td><td>${evidenceLinks(f.evidence_ids)}</td></tr>`))}</div>` : ""}

    <div class="card">
      <h2>7. Final assessment</h2>
      ${finalTable(fa, horizons)}
    </div>

    ${section("1. Company overview", overviewSection(d.company_overview), true)}
    ${section("2. Financial performance", financialSection(d.financial_performance))}
    ${section("Peer comparison", peerSection(d.peer_comparison))}
    ${section("3. Valuation", valuationSection(d.valuation))}
    ${section("4. Management and governance", managementSection(d.management_governance))}
    ${section("5. Growth prospects", growthSection(d.growth_prospects))}
    ${section("6. Risks", riskSection(d.risks))}
    ${section("Monitoring and open questions", `<h3>Monitor next</h3>${list(d.monitor_next)}
      <h3>Catalysts mentioned in the analysis</h3>${list(d.catalysts)}<h3>Open questions</h3>${list(d.open_questions)}`)}
    ${section(`Evidence (${(d.evidence || []).length})`, evidenceSection(d.evidence), false, "evidence")}
    ${section(`Claims (${(d.claims || []).length})`, claimsSection(d.claims))}
    ${section("Data quality limitations", list(d.data_quality_limitations), (d.data_quality_limitations || []).length > 0)}
    <p class="note small">${esc(d.disclaimer)}</p>`;
}

function horizonCard(h) {
  const tone = CLASS_TONE[h.classification] ?? "";
  return `<div class="card horizon ${tone}">
    <div class="row" style="align-items:center">
      <div class="grow"><h3 style="margin:0">${esc(h.horizon_label)} · ${esc(h.years)} year${h.years === 1 ? "" : "s"}</h3>
        <div style="margin-top:6px">${classBadge(h.classification, h.label)}</div></div>
      <div class="score">${h.score === null || h.score === undefined ? "–" : num(h.score, 1)}<span class="muted small">/100</span></div>
    </div>
    <p class="small muted" style="margin-top:6px">${esc(h.meaning)}</p>
    ${h.main_concern ? `<div class="concern"><strong>Main concern:</strong> ${esc(h.main_concern)}</div>` : ""}
    ${list(h.reasons)}
    ${h.category_scores ? `<h3>Category scores</h3>${kv(h.category_scores, 1)}` : ""}
  </div>`;
}

function finalTable(fa, horizons) {
  const rows = ASSESSMENT_ROWS.filter(([k]) => fa[k]).map(([k, label]) => {
    const it = fa[k];
    return `<tr><td><strong>${esc(label)}</strong></td><td>${ratingBadge(it.rating)}</td>
      <td class="num">${it.score === null || it.score === undefined ? "–" : num(it.score, 1)}</td>
      <td>${list(it.reasons)}</td><td>${evidenceLinks(it.evidence_ids)}</td></tr>`;
  });
  for (const h of horizons) {
    if (h.valuation && horizons.length > 1) {
      rows.push(`<tr><td><strong>Valuation (${esc(h.horizon_label.toLowerCase())})</strong></td><td>${ratingBadge(h.valuation.rating)}</td>
        <td class="num">${num(h.valuation.score, 1)}</td><td>${list(h.valuation.reasons)}</td><td>${evidenceLinks(h.valuation.evidence_ids)}</td></tr>`);
    }
    rows.push(`<tr><td><strong>Overall (${esc(h.horizon_label.toLowerCase())})</strong></td><td>${classBadge(h.classification, h.label)}</td>
      <td class="num">${h.score === null || h.score === undefined ? "–" : num(h.score, 1)}</td><td>${list(h.reasons)}</td><td></td></tr>`);
  }
  return table(["Category", "Rating", { label: "Score", cls: "num" }, "Why", "Evidence"], rows);
}

function section(title, body, open = false, id = "") {
  return `<details class="section" ${open ? "open" : ""} ${id ? `id="${id}"` : ""}><summary>${esc(title)}</summary><div class="body">${body}</div></details>`;
}

const narrative = (text) => (text ? `<p>${esc(text)}</p>` : `<p class="muted">No narrative (LLM analysis was not run or failed).</p>`);

function overviewSection(o = {}) {
  return `<h3>What it does</h3>${narrative(o.what_it_does)}
    <h3>Revenue model</h3>${narrative(o.revenue_model)}
    <h3>Competitive position</h3>${narrative(o.competitive_position)}
    <h3>Competitive advantages</h3>${list(o.competitive_advantages)}`;
}

function financialSection(f = {}) {
  const annual = f.annual_inr_crore || {};
  const years = [...new Set(Object.values(annual).flatMap((s) => Object.keys(s)))].sort();
  const annualTable = table(
    ["₹ crore", ...years.map((y) => ({ label: y, cls: "num" }))],
    Object.entries(annual).map(([m, s]) => `<tr><td>${esc(metricName(m))}</td>${years.map((y) => `<td class="num">${num(s[y], 0)}</td>`).join("")}</tr>`),
    { empty: "No annual figures." },
  );
  const rules = f.rules || [];
  return `<p class="muted">${esc(f.years_covered ?? "?")} year(s) of data.</p>
    <h3>Headline metrics</h3>${metricGrid(f.headline_metrics)}
    <h3>Annual figures</h3>${annualTable}
    <h3>Commentary</h3>${narrative(f.commentary)}
    <h3>Screening rules</h3>${table(["Rule", "Stage", "Status", "Observed", "Threshold", "Detail"], rules.map((r) => `<tr>
      <td class="mono small">${esc(r.rule_id)}${r.hard ? " <span class='badge'>hard</span>" : ""}</td><td>${esc(r.stage)}</td><td>${badge(r.status)}</td>
      <td class="num">${esc(typeof r.observed === "number" ? num(r.observed, 3) : r.observed ?? "–")}</td>
      <td class="num">${esc(typeof r.threshold === "number" ? num(r.threshold, 3) : r.threshold ?? "–")}</td><td class="small">${esc(r.message)}</td></tr>`))}
    ${(f.missing_score_components || []).length ? `<h3>Missing score components (scored 0)</h3>${list(f.missing_score_components.map(metricName))}` : ""}`;
}

function peerSection(p = {}) {
  const rows = Object.entries(p.metrics || {}).map(([k, m]) => {
    const isMultiple = ["pe", "pb", "ev_ebitda", "debt_to_equity"].includes(k);
    const f = (v) => (isMultiple ? (v === null || v === undefined ? "–" : `${num(v, 2)}x`) : pct(v));
    return `<tr><td>${esc(metricName(k))}</td><td class="num">${f(m.value)}</td><td class="num">${f(m.peer_median)}</td>
      <td class="num">${m.percentile === null || m.percentile === undefined ? "–" : num(m.percentile, 0)}</td><td class="num">${esc(m.peer_count)}</td></tr>`;
  });
  return `<p class="muted">Peers: ${(p.peers || []).length ? esc(p.peers.join(", ")) : "none with usable data (run a screening first)"}</p>
    ${table(["Metric", { label: "Company", cls: "num" }, { label: "Peer median", cls: "num" }, { label: "Percentile", cls: "num" }, { label: "Peers", cls: "num" }], rows)}`;
}

function valuationSection(v = {}) {
  const cur = v.current || {};
  const fv = v.fair_value_range;
  const scen = Object.entries(v.scenarios_by_horizon || {});
  const hist = v.history || {};
  return `
    <div class="grid">
      ${["pe", "pb", "ev_ebitda"].map((k) => `<div class="stat"><div class="k">${metricName(k)}</div><div class="v">${cur[k] === null || cur[k] === undefined ? "–" : `${num(cur[k], 1)}x`}</div>
        <div class="p">sector median ${v.sector_median?.[k] ? `${num(v.sector_median[k], 1)}x` : "n/a"}</div></div>`).join("")}
      <div class="stat"><div class="k">Last price</div><div class="v">₹${num(cur.last_price, 2)}</div><div class="p">earnings basis ${esc(v.earnings_basis || "–")}</div></div>
      <div class="stat"><div class="k">Market cap</div><div class="v">₹${num(cur.market_cap_cr, 0)} cr</div></div>
    </div>
    ${hist.median !== undefined ? `<h3>Own history (${esc(v.primary_metric?.toUpperCase())})</h3>
      <p>Median ${num(hist.median, 1)}x; current sits at the ${num(hist.current_percentile, 0)}th percentile of ${Object.keys(hist.by_period || {}).length} year(s).</p>` : ""}
    <h3>Fair-value range</h3>
    ${fv ? `${table(["Low", "Mid", "High", "Price now"].map((l) => ({ label: l, cls: "num" })),
      [`<tr><td class="num">₹${num(fv.low, 2)}</td><td class="num">₹${num(fv.mid, 2)}</td><td class="num">₹${num(fv.high, 2)}</td><td class="num">₹${num(fv.price, 2)}</td></tr>`])}
      <p class="small muted">${esc(fv.basis)}</p>` : `<p class="muted">Not available (needs sector or history multiples).</p>`}
    <h3>Scenarios</h3>
    ${scen.length ? scen.map(([h, s]) => scenarioTable(h, s)).join("") : `<p class="muted">Not available.</p>`}
    ${v.scenario_commentary ? `<p>${esc(v.scenario_commentary)}</p>` : ""}
    <h3>Commentary</h3>${narrative(v.commentary)}
    ${v.medium_term_view ? `<h3>Medium-term view</h3><p>${esc(v.medium_term_view)}</p>` : ""}
    <h3>Assumptions</h3>${list(v.assumptions)}
    <h3>Limitations</h3>${list(v.limitations)}`;
}

function scenarioTable(horizon, s) {
  if (!s) return "";
  const rows = ["conservative", "base", "optimistic"].filter((n) => s[n]).map((n) => {
    const r = s[n];
    return `<tr><td>${esc(titleCase(n))}</td><td class="num">${signedPct(r.annual_growth)}</td><td class="num">${num(r.exit_multiple, 1)}x</td>
      <td class="num">₹${num(r.value_per_share_today, 0)}</td><td class="num">₹${num(r.value_per_share_at_horizon, 0)}</td>
      <td class="num"><strong>${signedPct(r.implied_annual_price_change)}</strong></td></tr>`;
  });
  return `<p><strong>${esc(titleCase(horizon))}</strong> <span class="muted">· ${esc(s.years)} years from ₹${num(s.price, 2)} ·
      ${esc(s.per_share_basis)} ₹${num(s.per_share, 2)}</span></p>
    ${table(["Scenario", { label: "Growth / yr", cls: "num" }, { label: "Exit multiple", cls: "num" }, { label: "Value today", cls: "num" },
      { label: "Value at horizon", cls: "num" }, { label: "Implied return / yr", cls: "num" }], rows)}`;
}

function managementSection(m = {}) {
  const hist = m.shareholding_history || [];
  const cols = hist.length ? Object.keys(hist[0]).filter((k) => k !== "period_end") : [];
  return `<h3>Promoter</h3>${metricGrid(m.promoter)}
    <h3>Shareholding history</h3>${table(["Quarter", ...cols.map((c) => ({ label: titleCase(c), cls: "num" }))],
      hist.map((h) => `<tr><td>${esc(h.period_end)}</td>${cols.map((c) => `<td class="num">${typeof h[c] === "number" ? num(h[c], 2) : esc(h[c] ?? "–")}</td>`).join("")}</tr>`))}
    <h3>Governance flags</h3>${table(["Flag", "Severity", "Detail"], (m.flags || []).map((f) => `<tr><td class="mono small">${esc(f.code)}</td>
      <td>${badge(f.severity)}</td><td>${esc(f.message)}</td></tr>`), { empty: "No governance flags." })}
    <h3>Capital allocation</h3>${metricGrid(m.capital_allocation)}
    <h3>Assessment</h3>${narrative(m.commentary)}
    <h3>Not covered</h3>${list(m.not_covered)}`;
}

function growthSection(g = {}) {
  const eo = g.earnings_outlook;
  const cat = g.catalysts;
  return `<h3>Earnings outlook</h3>
    ${eo ? `<p>${ratingBadge(eo.rating)} <span class="muted small">basis: ${esc(eo.basis || "–")}</span></p>${list(eo.reasons)}` : `<p class="muted">Not available.</p>`}
    <h3>Recent momentum</h3>${metricGrid(g.recent_momentum)}
    <h3>Catalysts</h3>
    ${cat ? `<p>${ratingBadge(cat.rating)} <span class="muted small">${esc(cat.note)}</span></p>
      ${table(["Date", "Type", "Detail", "Evidence"], (cat.items || []).map((c) => `<tr><td>${esc(c.date || "")}</td><td>${esc(titleCase(c.category || c.type || ""))}</td>
        <td>${esc(c.title || c.description || "")}</td><td>${evidenceLinks(c.evidence_id ? [c.evidence_id] : c.evidence_ids)}</td></tr>`), { empty: "No evidenced catalysts." })}`
      : `<p class="muted">Not available.</p>`}
    <h3>Industry outlook</h3>${narrative(g.industry_outlook)}
    ${g.industry_trend ? `<h3>Industry earnings trend</h3>${kv(g.industry_trend)}` : ""}
    <h3>Growth drivers</h3>${list(g.growth_drivers)}
    <h3>Growth-related filings</h3>${table(["Date", "Category", "Title", "Evidence"], (g.growth_filings || []).map((f) => `<tr><td>${esc(f.date)}</td>
      <td>${esc(titleCase(f.category))}</td><td>${esc(f.title)}</td><td>${evidenceLinks(f.evidence_id ? [f.evidence_id] : [])}</td></tr>`), { empty: "None found." })}
    <h3>Competitive threats</h3>${list(g.competitive_threats)}`;
}

function riskSection(r = {}) {
  return `${table(["Category", "Severity", "Risk", "Evidence"], (r.items || []).map((i) => `<tr><td>${esc(titleCase(i.category))}</td><td>${badge(i.severity)}</td>
      <td>${esc(i.description)}</td><td>${evidenceLinks(i.evidence_ids)}</td></tr>`), { empty: "No risk analysis (LLM not run) beyond the red flags and rules above." })}
    <h3>Downside scenarios</h3>${list(r.downside_scenarios)}
    <h3>The thesis no longer holds if…</h3>${list(r.invalidation_conditions)}`;
}

function evidenceSection(items = []) {
  return table(["Id", "Source", "Title", "Published", "Retrieved"], items.map((e) => {
    const url = safeUrl(e.url);
    const title = esc(e.title || e.url || "(untitled)");
    return `<tr class="ev-item" id="ev-${esc(e.id)}"><td class="ev">${esc(e.id)}</td><td class="small">${esc(e.provider)}<br><span class="muted">${esc(titleCase(e.source_type))}</span>
      ${e.is_synthetic ? `<br>${badge("synthetic", "warn")}` : ""}</td>
      <td>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title}</td>
      <td class="small">${esc(e.published_at ? e.published_at.slice(0, 10) : "–")}</td><td class="small">${esc(e.retrieved_at?.slice(0, 10))}</td></tr>`;
  }), { empty: "No evidence recorded." });
}

function claimsSection(claims = []) {
  return table(["", "Section", "Claim", "Evidence", "Problems"], claims.map((c) => `<tr><td>${c.verified ? badge("verified", "good") : badge("unverified", "bad")}</td>
    <td>${esc(c.section)}</td><td>${esc(c.statement)} <span class="muted small">(${esc(c.materiality)})</span></td>
    <td>${evidenceLinks(c.evidence_ids)}</td><td class="small">${esc((c.problems || []).join("; "))}</td></tr>`), { empty: "No claims (narrative analysis not run)." });
}

async function shortlistView(params) {
  const horizon = params.get("h") === "medium_term" ? "medium_term" : "long_term";
  view.innerHTML = `
    <div class="row" style="align-items:center;margin-bottom:12px">
      <h1 class="grow" style="margin:0">Ranked shortlist</h1>
      <label>Rank by
        <select id="h"><option value="long_term">Long term (5–10 years)</option><option value="medium_term">Medium term (1–3 years)</option></select></label>
    </div>
    <p class="muted">Latest report per company whose ${horizon === "long_term" ? "long-term" : "medium-term"} classification is a candidate class;
      best classification first, then score. Click a row for the full report.</p>
    <div class="card" id="sl"><span class="spinner"></span></div>`;
  const sel = document.getElementById("h");
  sel.value = horizon;
  sel.addEventListener("change", () => { location.hash = `#/shortlist?h=${sel.value}`; });
  try {
    const rows = await api("/research/shortlist", { params: { horizon } });
    document.getElementById("sl").innerHTML = table(
      [{ label: "#", cls: "num" }, "Company", "Long term", "Medium term", { label: "Score", cls: "num" }, "Main concern", { label: "Red flags", cls: "num" }, "As of"],
      rows.map((r) => `<tr class="clickable" data-href="#/reports/${r.report_id}"><td class="num">${r.rank}</td>
        <td><strong>${esc(r.symbol)}</strong><br><span class="small muted">${esc(r.name)}${r.sector ? ` · ${esc(r.sector)}` : ""}</span></td>
        <td>${labelBadge(r.long_term)}</td><td>${labelBadge(r.medium_term)}</td>
        <td class="num">${r.score === null ? "–" : num(r.score, 1)}</td><td class="small">${esc(r.main_concern || "")}</td>
        <td class="num">${r.red_flags ? `<span class="badge bad">${r.red_flags}</span>` : "0"}</td><td class="small">${esc(r.as_of_date)}</td></tr>`),
      { empty: "Shortlist is empty. Run discovery, then research the top candidates." },
    );
  } catch (e) {
    document.getElementById("sl").innerHTML = errorView(e);
  }
}

async function discoveryView() {
  view.innerHTML = `
    <h1>Discovery</h1>
    <div class="grid-2">
      <form class="card" id="screen-form">
        <h2>1. Screen the universe</h2>
        <p class="small muted">Applies quality and risk filters to every eligible company and ranks the candidates. Fetches data for each company, so a full run takes a while.</p>
        <div class="row">
          <label>Rank by<select name="horizon"><option value="long_term">Long term</option><option value="medium_term">Medium term</option></select></label>
          <label>Queue top N for research<input name="enqueue_top_n" type="number" min="0" max="200" value="5" style="width:90px"></label>
          <label>As of<input name="as_of_date" type="date"></label>
          <button class="primary" type="submit">Run screening</button>
        </div>
      </form>
      <form class="card" id="queue-form">
        <h2>2. Research the queue</h2>
        <p class="small muted">Researches queued candidates in depth. Strong results join the auto-shortlist watchlist for monitoring.</p>
        <div class="row">
          <label>How many<input name="limit" type="number" min="1" max="50" value="5" style="width:80px"></label>
          <button class="primary" type="submit">Process queue</button>
        </div>
        <div id="queue-out" class="small" style="margin-top:8px"></div>
      </form>
    </div>
    <div class="card"><h2>Screening runs</h2><div id="runs"><span class="spinner"></span></div></div>`;

  const screen = document.getElementById("screen-form");
  screen.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(screen);
    const body = { horizon: f.get("horizon"), enqueue_top_n: Number(f.get("enqueue_top_n") || 0) };
    if (f.get("as_of_date")) body.as_of_date = f.get("as_of_date");
    busy(screen.querySelector("button"), "Screening…", async () => {
      const run = await api("/screening/runs", { method: "POST", body });
      location.hash = `#/discovery/runs/${run.id}`;
    });
  });
  const queue = document.getElementById("queue-form");
  queue.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(queue.querySelector("button"), "Researching…", async () => {
      const out = await api("/research/queue/process", { method: "POST", params: { limit: new FormData(queue).get("limit") } });
      document.getElementById("queue-out").innerHTML = `Processed ${out.processed}: ${out.succeeded} succeeded, ${out.failed} failed.
        ${out.newly_monitored.length ? `Now monitoring ${esc(out.newly_monitored.join(", "))}.` : ""}
        ${out.report_ids.length ? `<a href="#/shortlist">Open the shortlist →</a>` : ""}`;
    });
  });

  try {
    const runs = await api("/screening/runs");
    document.getElementById("runs").innerHTML = table(
      ["#", "Run at", "As of", "Status", { label: "Universe", cls: "num" }, { label: "Candidates", cls: "num" }, "Rules"],
      runs.map((r) => `<tr class="clickable" data-href="#/discovery/runs/${r.id}"><td>${r.id}</td><td class="small">${esc(date(r.run_at))}</td>
        <td>${esc(r.as_of_date)}</td><td>${badge(r.status)}</td><td class="num">${r.universe_count}</td><td class="num">${r.candidate_count}</td>
        <td class="small mono">${esc(r.rules_version)}</td></tr>`),
      { empty: "No screening runs yet." },
    );
  } catch (e) {
    document.getElementById("runs").innerHTML = errorView(e);
  }
}

async function runView(id, params) {
  const status = params.get("status") || "candidate";
  view.innerHTML = `<p><span class="spinner"></span> Loading run #${esc(id)}…</p>`;
  let run;
  try { run = await api(`/screening/runs/${encodeURIComponent(id)}`, { params: { result_status: status === "all" ? undefined : status } }); } catch (e) { view.innerHTML = errorView(e); return; }
  const counts = run.summary?.status_counts || {};
  view.innerHTML = `
    <p class="small"><a href="#/discovery">← Discovery</a></p>
    <div class="card">
      <h1>Screening run #${run.id} ${badge(run.status)}</h1>
      <p class="muted">As of ${esc(run.as_of_date)} · rules ${esc(run.rules_version)} · universe ${esc(run.universe_version)} ·
        ranked by ${esc(titleCase(run.summary?.ranked_by || "long_term"))} · queued ${esc(run.summary?.enqueued_for_research ?? 0)} for research</p>
      ${run.error ? `<p class="alert-box">${esc(run.error)}</p>` : ""}
      ${kv(counts)}
    </div>
    <div class="card">
      <div class="row" style="align-items:center;margin-bottom:8px">
        <h2 class="grow" style="margin:0">Results</h2>
        <label>Show<select id="st">${["candidate", "governance_review", "rejected", "ineligible", "all"].map((s) => `<option value="${s}">${titleCase(s)}</option>`).join("")}</select></label>
      </div>
      ${table([{ label: "Rank", cls: "num" }, "Company", "Status", { label: "Score", cls: "num" }, "Failed or flagged rules", ""],
        run.results.map((r) => `<tr><td class="num">${r.rank ?? "–"}</td><td><strong>${esc(r.symbol)}</strong><br><span class="small muted">${esc(r.name)}${r.sector ? ` · ${esc(r.sector)}` : ""}</span></td>
          <td>${badge(r.status)}</td><td class="num">${r.score === null ? "–" : num(r.score, 1)}</td>
          <td class="small">${esc([...(r.exclusion_reasons || []), ...(r.failed_rules || []).map((f) => f.message || f.rule_id || f)].slice(0, 3).join("; "))}</td>
          <td><button class="link" data-research="${esc(r.symbol)}">Research</button></td></tr>`),
        { empty: "No results with this status." })}
    </div>`;
  const st = document.getElementById("st");
  st.value = status;
  st.addEventListener("change", () => { location.hash = `#/discovery/runs/${id}?status=${st.value}`; });
}

async function watchlistsView() {
  view.innerHTML = `
    <div class="row" style="align-items:center;margin-bottom:12px">
      <h1 class="grow" style="margin:0">Watchlists</h1>
      <form id="wl-form" class="row"><input name="name" required maxlength="128" placeholder="New watchlist name"><button type="submit">Create</button></form>
    </div>
    <div id="wls"><span class="spinner"></span></div>`;
  const form = document.getElementById("wl-form");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(form.querySelector("button"), "Creating…", async () => {
      const wl = await api("/watchlists", { method: "POST", body: { name: new FormData(form).get("name").trim() } });
      location.hash = `#/watchlists/${wl.id}`;
    });
  });
  try {
    const wls = await api("/watchlists");
    document.getElementById("wls").innerHTML = wls.length
      ? `<div class="grid-2">${wls.map((w) => `<a class="card" href="#/watchlists/${w.id}" style="color:inherit;text-decoration:none">
          <h2>${esc(w.name)}</h2><p class="muted">${w.companies.length} compan${w.companies.length === 1 ? "y" : "ies"}
          ${w.companies.some((c) => c.needs_review) ? ` · ${badge("needs review", "warn")}` : ""}</p>
          <p class="small">${esc(w.companies.map((c) => c.symbol).join(", "))}</p></a>`).join("")}</div>`
      : `<p class="empty">No watchlists yet.</p>`;
  } catch (e) {
    document.getElementById("wls").innerHTML = errorView(e);
  }
}

async function watchlistView(id) {
  let wl;
  try { wl = await api(`/watchlists/${encodeURIComponent(id)}`); } catch (e) { view.innerHTML = errorView(e); return; }
  view.innerHTML = `
    <p class="small"><a href="#/watchlists">← Watchlists</a></p>
    <h1>${esc(wl.name)}</h1>
    <form class="card" id="add-form">
      <h2>Add or update a company</h2>
      <div class="row">
        <label>Symbol<input name="symbol" required maxlength="32" placeholder="ASIANPAINT" style="width:150px"></label>
        <label class="grow">Thesis<input name="thesis" placeholder="Why you are watching it"></label>
        <label>Review date<input name="review_date" type="date"></label>
        <button class="primary" type="submit">Save</button>
      </div>
    </form>
    ${wl.companies.length ? wl.companies.map((c) => `<div class="card">
      <div class="row" style="align-items:center">
        <h2 class="grow" style="margin:0">${esc(c.symbol)} <span class="muted small">${esc(c.name)}</span></h2>
        ${c.needs_review ? badge("needs review", "warn") : ""}
        <a href="#/research?q=${encodeURIComponent(c.symbol)}">Reports</a>
        <button class="danger" data-remove="${esc(c.symbol)}">Remove</button>
      </div>
      <p style="margin-top:8px">${c.thesis ? esc(c.thesis) : `<span class="muted">No thesis.</span>`}</p>
      ${c.assumptions?.length ? `<h3>Assumptions</h3>${list(c.assumptions)}` : ""}
      ${c.invalidation_conditions?.length ? `<h3>Invalidation conditions</h3>${list(c.invalidation_conditions.map((i) => `${metricName(i.metric)} ${i.op} ${i.value}${i.description ? ` (${i.description})` : ""}`))}` : ""}
      ${c.valuation_range ? `<h3>Valuation range</h3><p>${esc(c.valuation_range.metric?.toUpperCase())} ${esc(c.valuation_range.low)}–${esc(c.valuation_range.high)}: ${esc(c.valuation_range.assumptions)}</p>` : ""}
      <p class="small muted">Added ${esc(date(c.added_at))} · last checked ${esc(date(c.last_checked_at))}${c.review_date ? ` · review by ${esc(c.review_date)}` : ""}</p>
    </div>`).join("") : `<p class="empty">No companies yet.</p>`}`;

  const form = document.getElementById("add-form");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const body = { symbol: f.get("symbol").trim() };
    if (f.get("thesis")) body.thesis = f.get("thesis");
    if (f.get("review_date")) body.review_date = f.get("review_date");
    busy(form.querySelector("button"), "Saving…", async () => {
      await api(`/watchlists/${id}/companies`, { method: "PUT", body });
      toast(`${body.symbol.toUpperCase()} saved.`);
      watchlistView(id);
    });
  });
  view.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", () => {
    if (!confirm(`Remove ${b.dataset.remove} from ${wl.name}?`)) return;
    busy(b, "Removing…", async () => {
      await api(`/watchlists/${id}/companies/${encodeURIComponent(b.dataset.remove)}`, { method: "DELETE" });
      watchlistView(id);
    });
  }));
}

async function alertsView() {
  view.innerHTML = `
    <div class="row" style="align-items:center;margin-bottom:12px">
      <h1 class="grow" style="margin:0">Alerts</h1>
      <button id="monitor" class="primary">Run monitoring now</button>
      <button id="deliver">Retry delivery</button>
    </div>
    <p class="muted">Monitoring checks every watchlist company for new results, governance events and broken invalidation conditions.</p>
    <div id="alerts"><span class="spinner"></span></div>`;
  const monitor = document.getElementById("monitor");
  monitor.addEventListener("click", () => busy(monitor, "Checking…", async () => {
    const out = await api("/alerts/monitor", { method: "POST" });
    toast(`Checked ${out.companies_checked} companies: ${out.alerts_created} new alert(s)${out.errors.length ? `, ${out.errors.length} error(s)` : ""}.`, out.errors.length > 0);
    alertsView();
  }));
  const deliver = document.getElementById("deliver");
  deliver.addEventListener("click", () => busy(deliver, "Delivering…", async () => {
    await api("/alerts/deliver", { method: "POST" });
    toast("Delivery retried.");
    alertsView();
  }));
  try {
    const alerts = await api("/alerts", { params: { limit: 100 } });
    document.getElementById("alerts").innerHTML = alerts.length ? alerts.map((a) => {
      const p = a.payload || {};
      return `<div class="card">
        <div class="row" style="align-items:center">
          <h2 class="grow" style="margin:0">${esc(a.symbol)} · ${esc(p.trigger || a.rule_id)}</h2>
          ${badge(a.severity)} ${badge(a.delivery_status)}
        </div>
        <p class="small muted" style="margin-top:4px">${esc(date(a.triggered_at))} · rule <span class="mono">${esc(a.rule_id)}</span>
          ${p.observed !== undefined && p.observed !== null ? ` · observed ${esc(p.observed)}` : ""}${p.threshold !== undefined && p.threshold !== null ? ` vs ${esc(p.threshold)}` : ""}</p>
        ${p.why_it_matters ? `<p><strong>Why it matters:</strong> ${esc(p.why_it_matters)}</p>` : ""}
        ${p.follow_up ? `<p><strong>Follow up:</strong> ${esc(p.follow_up)}</p>` : ""}
        ${(p.data_quality_warnings || []).length ? `<p class="small muted">${esc(p.data_quality_warnings.join(" "))}</p>` : ""}
      </div>`;
    }).join("") : `<p class="empty">No alerts.</p>`;
  } catch (e) {
    document.getElementById("alerts").innerHTML = errorView(e);
  }
}

async function reportsForSymbol(symbol) {
  view.innerHTML = `<p class="small"><a href="#/research">← Research</a></p><h1>Reports for ${esc(symbol)}</h1><div class="card" id="r"><span class="spinner"></span></div>`;
  try {
    document.getElementById("r").innerHTML = reportTable(await api("/research/reports", { params: { symbol } }));
  } catch (e) {
    document.getElementById("r").innerHTML = errorView(e);
  }
}

function settingsView() {
  const has = Boolean(getKey());
  view.innerHTML = `
    <h1>Settings</h1>
    <form class="card" id="key-form">
      <h2>API key</h2>
      <p class="muted">The <span class="mono">API_KEY</span> value from your <span class="mono">.env</span>. It is kept in this browser only and sent as the
        <span class="mono">X-API-Key</span> header to this server.</p>
      <div class="row">
        <label class="grow">Key<input name="key" type="password" autocomplete="off" placeholder="${has ? "A key is saved; enter a new one to replace it" : "Paste the API key"}"></label>
        <button class="primary" type="submit">Save</button>
        ${has ? `<button type="button" id="clear">Forget key</button>` : ""}
      </div>
      <p class="small" id="key-status" style="margin-top:8px">${has ? badge("key saved", "good") : badge("no key", "warn")}</p>
    </form>`;
  const form = document.getElementById("key-form");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const key = new FormData(form).get("key").trim();
    if (!key) return;
    setKey(key);
    busy(form.querySelector("button"), "Checking…", async () => {
      await api("/research/reports", { params: { limit: 1 } });
      toast("API key works.");
      location.hash = "#/research";
    });
  });
  document.getElementById("clear")?.addEventListener("click", () => { setKey(""); settingsView(); });
}

// ---------- routing ----------

const routes = [
  [/^#\/reports\/(\d+)$/, (m) => reportView(m[1])],
  [/^#\/shortlist$/, (m, p) => shortlistView(p)],
  [/^#\/discovery\/runs\/(\d+)$/, (m, p) => runView(m[1], p)],
  [/^#\/discovery$/, () => discoveryView()],
  [/^#\/watchlists\/(\d+)$/, (m) => watchlistView(m[1])],
  [/^#\/watchlists$/, () => watchlistsView()],
  [/^#\/alerts$/, () => alertsView()],
  [/^#\/settings$/, () => settingsView()],
  [/^#\/research$/, (m, p) => (p.get("q") ? reportsForSymbol(p.get("q")) : researchView())],
];

function route() {
  const [path, query = ""] = (location.hash || "#/research").split("?");
  const params = new URLSearchParams(query);
  if (!getKey() && path !== "#/settings") { location.hash = "#/settings"; return; }
  const tab = path.split("/")[1] === "reports" ? "research" : path.split("/")[1];
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  for (const [re, fn] of routes) {
    const m = path.match(re);
    if (m) { fn(m, params); window.scrollTo(0, 0); return; }
  }
  location.hash = "#/research";
}

// Row links, evidence jumps (open the evidence section first) and "Research" buttons on screening results.
view.addEventListener("click", (ev) => {
  const evLink = ev.target.closest("[data-ev]");
  if (evLink) {
    ev.preventDefault();
    const sec = document.getElementById("evidence");
    if (sec) sec.open = true;
    document.getElementById(`ev-${evLink.dataset.ev}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  const research = ev.target.closest("[data-research]");
  if (research) {
    busy(research, "Researching…", async () => {
      const out = await api("/research", { method: "POST", body: { query: research.dataset.research } });
      location.hash = `#/reports/${out.id}`;
    });
    return;
  }
  const row = ev.target.closest("tr[data-href]");
  if (row && !ev.target.closest("a, button")) location.hash = row.dataset.href;
});

window.addEventListener("hashchange", route);
route();
