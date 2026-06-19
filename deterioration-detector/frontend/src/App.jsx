import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceArea, Area, AreaChart, CartesianGrid,
} from "recharts";

const RISK_COLOR = { Low: "#2ea043", Medium: "#d29922", High: "#f85149" };
// Per-lab abnormality status → colour + label (matches src/analysis/abnormal.py).
const STATUS = {
  normal: { color: "#2ea043", label: "Normal" },
  abnormal: { color: "#d29922", label: "Abnormal" },
  critical: { color: "#f85149", label: "Critical" },
};
const TREND = {
  worsening: { icon: "▲", label: "worsening", color: "#f85149" },
  improving: { icon: "▼", label: "improving", color: "#2ea043" },
  stable: { icon: "–", label: "stable", color: "#8b98a5" },
};
const fmtTime = (iso) => iso.replace("T", " ").slice(0, 16);

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

  return (
    <div className="app">
      <div className="sidebar">
        <header className="top">
          <h1>🏥 Patient Deterioration Detector</h1>
          <p>Early-warning from lab trends · MIMIC-III LABEVENTS</p>
        </header>
        {stats && <StatsBar stats={stats} />}
        <div className="filters">
          {["High", "Medium", "Low", ""].map((c) => (
            <button key={c || "all"} className={filter === c ? "active" : ""}
              title={c ? TIPS.category : "Show every admission regardless of risk."}
              onClick={() => setFilter(c)}>{c || "All"}</button>
          ))}
        </div>
        <div className="controls">
          <input className="search" type="search" value={query}
            placeholder="🔍 Search patient / admission ID" title={TIPS.search}
            onChange={(e) => setQuery(e.target.value)} />
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
          {visible.map((a) => (
            <div key={`${a.subject_id}-${a.hadm_id}`}
              className={`row ${selected && selected.hadm_id === a.hadm_id ? "sel" : ""}`}
              onClick={() => setSelected(a)}>
              <div>
                <div className="pid">
                  {a.n_high > 0 && <span className="warn" title={TIPS.warn}>⚠</span>}
                  Patient {a.subject_id}
                </div>
                <div className="meta">
                  Adm {a.hadm_id} ·{" "}
                  <span title={TIPS.labs}>{a.n_measurements} labs</span> ·{" "}
                  <span title={TIPS.span}>{a.span_hours}h</span> ·{" "}
                  <span title={TIPS.critical}>{a.n_high} critical</span> ·{" "}
                  <span title={TIPS.worsening}>{a.n_worsening} worsening</span>
                </div>
              </div>
              <span className={`badge ${a.category}`} title={TIPS.badge}>{a.category} · {a.score}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="detail">
        {detailError && <div className="placeholder err">Couldn't load this patient — is the API running?</div>}
        {!detail && !detailError && <div className="placeholder">Loading patient…</div>}
        {detail && <Detail d={detail} />}
      </div>
    </div>
  );
}

function StatsBar({ stats }) {
  const p = stats.pipeline;
  return (
    <div className="stats">
      <Stat n={(+p.raw_rows).toLocaleString()} l="rows ingested" tip={TIPS.raw_rows} />
      <Stat n={(+p.kept_rows).toLocaleString()} l="clean values" tip={TIPS.kept_rows} />
      <Stat n={(+p.patients).toLocaleString()} l="patients" tip={TIPS.patients} />
      <Stat n={`${p.build_seconds}s`} l="pipeline time" tip={TIPS.build_seconds} />
    </div>
  );
}
const Stat = ({ n, l, tip }) => (
  <div className="stat">
    <div className="n">{n}</div>
    <div className="l">{tip ? <Tip text={tip}>{l}</Tip> : l}</div>
  </div>
);

function Detail({ d }) {
  const traj = d.trajectory.map((t) => ({ ...t, label: fmtTime(t.time) }));
  // status/trend per lab live in the risk breakdown, keyed by itemid.
  const byId = Object.fromEntries((d.risk.contributions || []).map((c) => [c.itemid, c]));
  return (
    <>
      <div className="card">
        <h2>Patient {d.subject_id} · Admission {d.hadm_id}</h2>
        <div className="riskhead">
          <Tip text={TIPS.riskScore}>
            <div className="big" style={{ color: RISK_COLOR[d.risk.category] }}>
              {d.risk.score}
            </div>
          </Tip>
          <span className={`badge ${d.risk.category}`} title={TIPS.category}>{d.risk.category} RISK</span>
        </div>
      </div>

      <div className="card">
        <h2><Tip text={TIPS.trajectory}>Risk trajectory over time</Tip></h2>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={traj}>
            <defs>
              <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f85149" stopOpacity={0.5} />
                <stop offset="100%" stopColor="#f85149" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#2a3540" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#8b98a5" }} minTickGap={40} />
            <YAxis tick={{ fontSize: 11, fill: "#8b98a5" }} />
            <Tooltip contentStyle={{ background: "#1a2129", border: "1px solid #2a3540" }} />
            <Area type="monotone" dataKey="score" stroke="#f85149" fill="url(#g)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2><Tip text={TIPS.breakdown}>Why this score?</Tip></h2>
        <Breakdown contributions={d.risk.contributions || []} />
      </div>

      <div className="card">
        <h2><Tip text={TIPS.alerts}>Early-warning alerts</Tip></h2>
        {d.alerts.length === 0 && <div className="placeholder" style={{ marginTop: 0 }}>No alerts</div>}
        {d.alerts.map((a, i) => (
          <div key={i} className={`alert ${a.level}`}>
            <span className={`dot ${a.level}`} />{a.message}
          </div>
        ))}
      </div>

      <div className="card">
        <h2><Tip text={TIPS.labTrends}>Lab trends ({d.labs.length} tests)</Tip></h2>
        <div className="labgrid">
          {d.labs.map((lab) => <LabChart key={lab.itemid} lab={lab} info={byId[lab.itemid]} />)}
        </div>
      </div>
    </>
  );
}

function Breakdown({ contributions }) {
  const drivers = contributions.filter((c) => c.points > 0);
  if (drivers.length === 0) {
    return <div className="placeholder" style={{ marginTop: 0 }}>All labs are within normal range — nothing driving up the risk.</div>;
  }
  return (
    <div className="breakdown">
      {drivers.map((c) => {
        const st = STATUS[c.status] || STATUS.normal;
        const tr = TREND[c.trend] || TREND.stable;
        return (
          <div key={c.itemid} className="brow">
            <span className="dot" style={{ background: st.color }} />
            <span className="bname">
              {GLOSSARY[c.test_name]
                ? <Tip text={GLOSSARY[c.test_name]}>{c.test_name}</Tip>
                : c.test_name}
            </span>
            <span className="bval">{(+c.latest_value).toPrecision(3) / 1} {c.unit}</span>
            <span className="bstatus" style={{ color: st.color }}>{st.label}</span>
            <span className="btrend" style={{ color: tr.color }}>{tr.icon} {tr.label}</span>
            <span className="bpts">+{c.points}</span>
          </div>
        );
      })}
    </div>
  );
}

function LabChart({ lab, info }) {
  const data = lab.points.map((p) => ({ label: fmtTime(p.time), value: p.value }));
  const def = GLOSSARY[lab.test_name];
  const st = STATUS[info?.status] || STATUS.normal;
  const title = (
    <span className="t">
      {lab.test_name} ({lab.unit})
      {info && <span className="lstatus" style={{ color: st.color }}> · {st.label}</span>}
    </span>
  );
  return (
    <div className="lab">
      {def ? <Tip text={def}>{title}</Tip> : title}
      <ResponsiveContainer width="100%" height={130}>
        <LineChart data={data}>
          <ReferenceArea y1={lab.normal_low} y2={lab.normal_high} fill="#2ea043" fillOpacity={0.12}
            label={{ value: "normal range", position: "insideTopLeft", fontSize: 9, fill: "#2ea043" }} />
          <XAxis dataKey="label" hide />
          <YAxis tick={{ fontSize: 9, fill: "#8b98a5" }} width={32} domain={["auto", "auto"]} />
          <Tooltip contentStyle={{ background: "#1a2129", border: "1px solid #2a3540", fontSize: 12 }} />
          <Line type="monotone" dataKey="value" stroke={st.color} strokeWidth={1.5}
            dot={{ r: 1.5 }} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
