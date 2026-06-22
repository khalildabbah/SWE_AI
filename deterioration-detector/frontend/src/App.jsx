import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceArea, Area, AreaChart, CartesianGrid,
} from "recharts";

// Clinical palette (mirrors styles.css tokens) for chart strokes/fills.
const RISK_COLOR = { Low: "#10b981", Medium: "#f59e0b", High: "#ef4444" };
// Per-lab abnormality status → colour + label (matches src/analysis/abnormal.py).
const STATUS = {
  normal: { color: "#10b981", label: "Normal" },
  abnormal: { color: "#f59e0b", label: "Abnormal" },
  critical: { color: "#ef4444", label: "Critical" },
};
const TREND = {
  worsening: { icon: "trending_up", arrow: "↑", label: "Worsening", cls: "worsening" },
  improving: { icon: "trending_down", arrow: "↓", label: "Improving", cls: "improving" },
  stable: { icon: "horizontal_rule", arrow: "", label: "Stable", cls: "stable" },
};
const NOTE = {
  High: "Critical threshold breached",
  Medium: "Elevated — monitor closely",
  Low: "Stable baseline",
};
const fmtTime = (iso) => iso.replace("T", " ").slice(0, 16);
const Icon = ({ name, className = "" }) => (
  <span className={`material-symbols-outlined ${className}`}>{name}</span>
);

// Plain-English explanations so non-clinical users understand every term on hover.
const GLOSSARY = {
  "Creatinine": "A waste product cleared by the kidneys. Rising levels suggest the kidneys aren't filtering blood well.",
  "Urea Nitrogen": "Also called BUN — a waste product from digesting protein. High levels can mean kidney stress or dehydration.",
  "Potassium": "An electrolyte that keeps the heart and muscles working. Too high or too low can trigger dangerous heart rhythms.",
  "Sodium": "An electrolyte that controls the body's water balance. Abnormal levels affect the brain and nerves.",
  "Bicarbonate": "Helps keep the blood's acid balance steady. Low levels mean the blood is turning too acidic — a sign of distress.",
  "White Blood Cells": "The body's infection-fighting cells. High counts often signal infection; very low counts weaken the immune system.",
  "Hematocrit": "The share of blood made up of red cells. Low values point to anemia or blood loss — less oxygen reaches the tissues.",
  "Lactate": "Builds up when tissues aren't getting enough oxygen. A rising level is a key warning sign of shock or severe illness.",
};

const TIPS = {
  riskScore: "A combined score built from how abnormal each lab is and whether it's trending worse. Higher means more concern.",
  category: "Triage category from the risk score: High patients should be looked at first.",
  trajectory: "How the patient's overall risk score has changed across their hospital stay.",
  alerts: "Plain-language warnings generated automatically when labs cross dangerous thresholds or keep worsening.",
  labTrends: "Each lab test plotted over time. The green band marks the normal, healthy range; the line is coloured by the latest value's status.",
  breakdown: "Exactly why this patient scored what they did — each lab's latest value, status, trend, and points added.",
  critical: "Lab values far outside the normal healthy range.",
  worsening: "Lab values trending in a dangerous direction over time.",
  labs: "Number of individual lab test results recorded for this admission.",
  span: "Hours between the patient's first and last lab measurement.",
  badge: "Risk category and score. Higher score = more concern; High patients need attention first.",
  warn: "This patient has one or more labs critically out of range.",
  search: "Filter the list by patient or admission ID.",
  sort: "Order the list by risk score, or by how much lab data each admission has.",
  raw_rows: "Total raw lab records read from the dataset before any cleaning.",
  kept_rows: "Records left after removing implausible or garbage values.",
  patients: "Number of distinct patients in the dataset.",
  build_seconds: "How long the data-processing pipeline took to run.",
};

// A small reusable hover tooltip with a dotted underline cue.
function Tip({ text, children }) {
  return (
    <span className="tip" tabIndex={0}>
      {children}
      <span className="tipbox" role="tooltip">{text}</span>
    </span>
  );
}

export default function App() {
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState("High");
  const [sort, setSort] = useState("score");
  const [query, setQuery] = useState("");
  const [board, setBoard] = useState([]);
  const [boardLoading, setBoardLoading] = useState(true);
  const [boardError, setBoardError] = useState(false);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState(false);

  useEffect(() => {
    fetch("/api/stats").then((r) => r.json()).then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    setBoardLoading(true);
    setBoardError(false);
    const params = new URLSearchParams({ limit: "100", sort });
    if (filter) params.set("category", filter);
    fetch(`/api/admissions?${params}`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => setBoard(d.items))
      .catch(() => { setBoard([]); setBoardError(true); })
      .finally(() => setBoardLoading(false));
  }, [filter, sort]);

  // Client-side search over the loaded cohort (by patient or admission ID).
  const visible = useMemo(() => {
    const q = query.trim();
    if (!q) return board;
    return board.filter((a) =>
      String(a.subject_id).includes(q) || String(a.hadm_id).includes(q));
  }, [board, query]);

  // Auto-select the top visible patient so the detail pane is never empty.
  // Keep the current selection if it's still in the visible list.
  useEffect(() => {
    if (!visible.length) return;
    setSelected((cur) =>
      cur && visible.some((a) => a.subject_id === cur.subject_id && a.hadm_id === cur.hadm_id)
        ? cur : visible[0]
    );
  }, [visible]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    setDetail(null);
    setDetailError(false);
    fetch(`/api/admissions/${selected.subject_id}/${selected.hadm_id}`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setDetail)
      .catch(() => setDetailError(true));
  }, [selected]);

  // Keyboard navigation: ↑/↓ move through the visible list.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      if (e.target.tagName === "INPUT") return;
      if (!visible.length) return;
      e.preventDefault();
      const i = visible.findIndex((a) =>
        selected && a.subject_id === selected.subject_id && a.hadm_id === selected.hadm_id);
      const next = e.key === "ArrowDown"
        ? Math.min(visible.length - 1, i + 1)
        : Math.max(0, i - 1);
      setSelected(visible[next]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, selected]);

  const FILTERS = [["High", "High"], ["Medium", "Med"], ["Low", "Low"], ["", "All"]];

  return (
    <div className="app">
      {/* ── Side navigation rail + patient explorer ── */}
      <aside className="rail">
        <div className="brand">
          <Icon name="monitor_heart" />
          <div>
            <h1>Clinical Control</h1>
            <div className="sub">Deterioration Watch</div>
          </div>
        </div>

        <nav className="nav">
          <a className="active"><Icon name="dashboard" /><span>Dashboard</span></a>
          <a><Icon name="monitor_heart" /><span>Patient Monitoring</span></a>
          <a><Icon name="warning" /><span>Risk Alerts</span></a>
        </nav>

        <div className="explorer">
          <div className="searchwrap">
            <Icon name="search" />
            <input className="search" type="search" value={query}
              placeholder="Search patient / admission ID" title={TIPS.search}
              onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="filters">
            {FILTERS.map(([c, label]) => (
              <button key={c || "all"} className={filter === c ? "active" : ""}
                title={c ? TIPS.category : "Show every admission regardless of risk."}
                onClick={() => setFilter(c)}>{label}</button>
            ))}
          </div>
          <div className="sortwrap">
            <select className="sort" value={sort} title={TIPS.sort}
              onChange={(e) => setSort(e.target.value)}>
              <option value="score">Sort: risk score</option>
              <option value="measurements">Sort: most lab data</option>
            </select>
          </div>

          <div className="list">
            {boardLoading && <div className="placeholder small">Loading admissions…</div>}
            {boardError && <div className="placeholder small err">Couldn't load admissions — is the API running?</div>}
            {!boardLoading && !boardError && visible.length === 0 && (
              <div className="placeholder small">
                {query ? `No admissions match “${query}”.` : "No admissions in this category."}
              </div>
            )}
            {visible.map((a) => {
              const sel = selected && selected.subject_id === a.subject_id && selected.hadm_id === a.hadm_id;
              return (
                <div key={`${a.subject_id}-${a.hadm_id}`}
                  className={`prow ${sel ? "sel" : ""}`} onClick={() => setSelected(a)}>
                  <div className="top">
                    <span className={`pid ${a.n_high > 0 ? "crit" : ""}`}>
                      {a.n_high > 0 && <Icon name="warning" />}
                      Patient {a.subject_id}
                    </span>
                    <span className={`chip ${a.category}`} title={TIPS.badge}>
                      {a.category} · <span className="pts">{a.score}</span>
                    </span>
                  </div>
                  <div className="meta" title={`${a.n_measurements} labs · ${a.span_hours}h · ${a.n_high} critical`}>
                    Adm {a.hadm_id} · {a.n_measurements} labs · {a.span_hours}h
                  </div>
                  {a.n_worsening > 0 && (
                    <div className="worse"><Icon name="history" />{a.n_worsening} worsening metric{a.n_worsening > 1 ? "s" : ""} detected</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="railfoot">
          <nav className="nav">
            <a><Icon name="help" /><span>Support</span></a>
            <a><Icon name="logout" /><span>Logout</span></a>
          </nav>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main className="main">
        <header className="topbar">
          <div className="lead">
            <span className="title">Deterioration Watch</span>
            <nav className="tabs">
              <span className="active">Active Cases</span>
              <span>Risk Distribution</span>
              <span>Unit Metrics</span>
            </nav>
          </div>
          <div className="actions">
            <div className="live"><span className="dot" />System Live</div>
            <Icon name="notifications" />
            <Icon name="apps" />
            <div className="avatar"><Icon name="person" /></div>
          </div>
        </header>

        <div className="canvas">
          {detailError && <div className="placeholder err">Couldn't load this patient — is the API running?</div>}
          {!detail && !detailError && <div className="placeholder">Loading patient…</div>}
          {detail && <Detail d={detail} meta={selected} />}
        </div>

        <footer className="databar">
          {stats ? <DataBar stats={stats} /> : <div className="seg">DB: MIMIC-III LABEVENTS</div>}
          <div className="seg">STATION: 4B-NC-01 · CLINICIAN: DR. SMITH</div>
        </footer>
      </main>
    </div>
  );
}

function DataBar({ stats }) {
  const p = stats.pipeline;
  return (
    <div className="seg">
      <Tip text={TIPS.raw_rows}><span>{(+p.raw_rows).toLocaleString()} ROWS</span></Tip>
      <Tip text={TIPS.kept_rows}><span>{(+p.kept_rows).toLocaleString()} CLEAN</span></Tip>
      <Tip text={TIPS.patients}><span>{(+p.patients).toLocaleString()} PATIENTS</span></Tip>
      <Tip text={TIPS.build_seconds}><span>ENGINE: {p.build_seconds}s</span></Tip>
    </div>
  );
}

function Detail({ d, meta }) {
  const cat = d.risk.category;
  const traj = d.trajectory.map((t) => ({ ...t, label: fmtTime(t.time) }));
  // status/trend per lab live in the risk breakdown, keyed by itemid.
  const byId = Object.fromEntries((d.risk.contributions || []).map((c) => [c.itemid, c]));
  const stroke = RISK_COLOR[cat];

  // Header metric cluster — real per-admission summary (from the board row).
  const nHigh = meta?.n_high ?? (d.risk.contributions || []).filter((c) => c.status === "critical").length;
  const nWorse = meta?.n_worsening ?? (d.risk.contributions || []).filter((c) => c.trend === "worsening").length;
  const nLabs = meta?.n_measurements ?? d.labs.reduce((s, l) => s + l.points.length, 0);
  const span = meta?.span_hours;

  return (
    <>
      {/* Bento header: score card + metric cluster */}
      <section className="bento">
        <div className={`panel scorecard ${cat}`}>
          <Icon name="warning" className="ghost" />
          <div>
            <div className="eyebrow">Current Risk Index</div>
            <h2>Patient {d.subject_id}</h2>
            <div className="adm">ADMISSION ID: {d.hadm_id}</div>
          </div>
          <div className="scorerow">
            <Tip text={TIPS.riskScore}><span className="big">{d.risk.score}</span></Tip>
            <div>
              <span className="badge" title={TIPS.category}>{cat} Risk</span>
              <div className="note">{NOTE[cat]}</div>
            </div>
          </div>
        </div>

        <div className="cluster">
          <div className="panel metric">
            <div className="label"><Tip text={TIPS.labs}>Labs Recorded</Tip></div>
            <div className="val">{(+nLabs).toLocaleString()}</div>
            <div className="delta ok"><Icon name="science" />this admission</div>
          </div>
          <div className="panel metric">
            <div className="label"><Tip text={TIPS.critical}>Critical Labs</Tip></div>
            <div className="val">{nHigh}</div>
            <div className={`delta ${nHigh > 0 ? "crit" : "ok"}`}>
              <Icon name={nHigh > 0 ? "priority_high" : "check"} />out of range
            </div>
          </div>
          <div className="panel metric">
            <div className="label"><Tip text={TIPS.worsening}>Worsening</Tip></div>
            <div className="val">{nWorse}</div>
            <div className={`delta ${nWorse > 0 ? "warn" : "ok"}`}>
              <Icon name={nWorse > 0 ? "trending_up" : "horizontal_rule"} />
              {span != null ? `over ${span}h` : "trending"}
            </div>
          </div>
        </div>
      </section>

      {/* Risk trajectory */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.trajectory}>Risk Trajectory Over Time</Tip></h3>
            <div className="desc">Combined deterioration index across the hospital stay</div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={traj} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.45} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#424754" strokeDasharray="4 4" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#8c909f", fontFamily: "Geist Mono" }} minTickGap={48} />
            <YAxis tick={{ fontSize: 11, fill: "#8c909f", fontFamily: "Geist Mono" }} width={36} />
            <Tooltip contentStyle={{ background: "#1c2b3c", border: "1px solid #424754", borderRadius: 6 }}
              labelStyle={{ color: "#c2c6d6" }} />
            <Area type="monotone" dataKey="score" stroke={stroke} fill="url(#g)" strokeWidth={3}
              dot={{ r: 2, fill: stroke }} activeDot={{ r: 5 }} />
          </AreaChart>
        </ResponsiveContainer>
      </section>

      {/* Why this score? — factor table */}
      <section className="panel factortable">
        <div className="head">
          <h3><Tip text={TIPS.breakdown}>Why this score?</Tip></h3>
          <div className="note"><Icon name="info" />Per-lab severity &amp; trend breakdown</div>
        </div>
        <FactorTable contributions={d.risk.contributions || []} />
      </section>

      {/* Early-warning alerts */}
      <section className="panel alerts">
        <h3><Icon name="emergency" /><Tip text={TIPS.alerts}>Early-Warning Alerts</Tip></h3>
        {d.alerts.length === 0
          ? <div className="placeholder small" style={{ margin: 0, textAlign: "left" }}>No alerts — all labs within range.</div>
          : (
            <div className="alertlist">
              {d.alerts.map((a, i) => (
                <div key={i} className={`alertrow ${a.level}`}>
                  <span className="dot" /><span className="msg">{a.message}</span>
                </div>
              ))}
            </div>
          )}
      </section>

      {/* Lab trends grid */}
      <section className="panel labpanel">
        <div className="head">
          <h3><Tip text={TIPS.labTrends}>Lab Trends ({d.labs.length} tests)</Tip></h3>
        </div>
        <div className="labgrid">
          {d.labs.map((lab) => <LabCard key={lab.itemid} lab={lab} info={byId[lab.itemid]} />)}
        </div>
      </section>
    </>
  );
}

function FactorTable({ contributions }) {
  const drivers = contributions.filter((c) => c.points > 0);
  if (drivers.length === 0) {
    return (
      <div style={{ padding: "22px 28px" }} className="placeholder small">
        All labs are within normal range — nothing driving up the risk.
      </div>
    );
  }
  return (
    <div className="tablewrap">
      <table className="factors">
        <thead>
          <tr>
            <th>Indicator</th>
            <th className="r">Value</th>
            <th>Status</th>
            <th>Trend</th>
            <th className="c">Score Impact</th>
          </tr>
        </thead>
        <tbody>
          {drivers.map((c) => {
            const st = STATUS[c.status] || STATUS.normal;
            const tr = TREND[c.trend] || TREND.stable;
            return (
              <tr key={c.itemid}>
                <td className="name">
                  <span className="lead">
                    <span className="dot" style={{ background: st.color }} />
                    {GLOSSARY[c.test_name]
                      ? <Tip text={GLOSSARY[c.test_name]}>{c.test_name}</Tip>
                      : c.test_name}
                  </span>
                </td>
                <td className="val">{(+c.latest_value).toPrecision(3) / 1}<span className="unit">{c.unit}</span></td>
                <td><span className={`statuspill ${c.status}`}>{st.label}</span></td>
                <td>
                  <span className={`trendcell ${tr.cls}`}>
                    <Icon name={tr.icon} />{tr.label}
                  </span>
                </td>
                <td className={`impact ${c.status}`}>+{c.points}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LabCard({ lab, info }) {
  const data = lab.points.map((p) => ({ label: fmtTime(p.time), value: p.value }));
  const def = GLOSSARY[lab.test_name];
  const status = info?.status || "normal";
  const st = STATUS[status] || STATUS.normal;
  const tr = TREND[info?.trend] || TREND.stable;
  const latest = lab.points.length ? lab.points[lab.points.length - 1].value : null;
  const name = `${lab.test_name} (${lab.unit})`;
  return (
    <div className={`labcard ${status}`}>
      <div className="lhead">
        <span className="lname">{def ? <Tip text={def}>{name}</Tip> : name}</span>
        <span className="lstat">{st.label}</span>
      </div>
      <div className="labbody">
        <ResponsiveContainer width="100%" height={128}>
          <LineChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
            <ReferenceArea y1={lab.normal_low} y2={lab.normal_high} fill="#10b981" fillOpacity={0.1} />
            <XAxis dataKey="label" hide />
            <YAxis tick={{ fontSize: 9, fill: "#8c909f", fontFamily: "Geist Mono" }} width={30} domain={["auto", "auto"]} />
            <Tooltip contentStyle={{ background: "#1c2b3c", border: "1px solid #424754", borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: "#c2c6d6" }} />
            <Line type="monotone" dataKey="value" stroke={st.color} strokeWidth={1.6}
              dot={{ r: 1.5 }} activeDot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
        {latest != null && (
          <div className="latest">
            {(+latest).toPrecision(3) / 1}
            {tr.arrow && <span className="arrow">{tr.arrow}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
