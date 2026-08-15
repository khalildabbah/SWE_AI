import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceArea, ReferenceLine, Area, AreaChart, CartesianGrid,
} from "recharts";
import Chatbot from "./Chatbot.jsx";
import Builder from "./Builder.jsx";

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
  syndromes: "Named clinical patterns detected when several labs move together — e.g. creatinine and urea both rising points at the kidneys. More telling than any single lab alone.",
  eval_accuracy: "Of all lab values, the share our detector classified (normal vs abnormal) the same way MIMIC's own flag did.",
  eval_precision: "When our detector calls a value abnormal, how often MIMIC agreed. Low precision means we over-flag.",
  eval_recall: "Of every value MIMIC flagged abnormal, how many our detector also caught. Also called sensitivity.",
  eval_specificity: "Of every value MIMIC considered normal, how many our detector also called normal.",
  eval_f1: "A single balance of precision and recall (their harmonic mean).",
  eval_cm: "Confusion matrix: each value falls into one of four buckets comparing our call against MIMIC's flag.",
  warn: "This patient has one or more labs critically out of range.",
  search: "Filter the list by patient or admission ID.",
  sort: "Order the list by risk score, or by how much lab data each admission has.",
  scoringPattern: "Which pattern decides the risk score. The built-in score counts all 8 labs equally. Pick a pattern you built and every score, badge and ranking is recomputed from that pattern's rules instead — so the list ranks patients by how much they look like that syndrome.",
  lead_time: "How many hours before the first critically out-of-range value our risk score had already escalated. The core early-warning question this project asks.",
  lt_concern: "First concern = the first time the score left Low (reached Medium or High). The earliest hint of trouble.",
  lt_alert: "High alert = the first time the score reached High, the top triage category.",
  lt_rate: "Of all admissions that reached a critical lab value, the share where the score escalated strictly before that value appeared.",
  lt_event: "Deterioration is proxied by the first critically out-of-range lab value, because this prototype ingests only LABEVENTS (no death / ICU-transfer outcomes).",
  raw_rows: "Total raw lab records read from the dataset before any cleaning.",
  kept_rows: "Records left after removing implausible or garbage values.",
  patients: "Number of distinct patients in the dataset.",
  build_seconds: "How long the data-processing pipeline took to run.",
  rb_ranges: "The normal healthy range for each lab. A value inside this range scores zero; outside it starts adding points.",
  rb_worsening: "The direction that signals deterioration for this lab — so the trend detector knows which way is dangerous.",
  rb_classification: "How far outside the normal range a value sits decides whether it's merely abnormal or critical.",
  rb_scoring: "The exact arithmetic that turns each lab's status and trend into the patient's overall risk score.",
  rb_categories: "The score cut-points that map a total into the Low / Medium / High triage category.",
  rb_syndromes: "Named clinical patterns that fire when several labs move together — each backed by a consensus definition.",
  rb_source: "The published source this rule is based on. Click to open it; hover for the full citation.",
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
  const [page, setPage] = useState("dashboard"); // "dashboard" | "monitoring"
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
  // Which pattern drives scoring. "" = the built-in 8-lab risk score.
  const [scoringPattern, setScoringPattern] = useState("");
  const [patterns, setPatterns] = useState([]);

  useEffect(() => {
    fetch("/api/stats").then((r) => r.json()).then(setStats).catch(() => {});
  }, []);

  // Saved patterns that can actually score — one needs at least one rule over a
  // lab this dataset carries, or there is nothing to rank patients by.
  const loadPatterns = () =>
    fetch("/api/builder/syndromes").then((r) => r.json())
      .then((d) => setPatterns((d.items || []).filter(
        (p) => (p.signals || []).some((s) => s.in_dataset && s.itemid != null))))
      .catch(() => {});

  useEffect(() => { loadPatterns(); }, []);

  // A pattern deleted elsewhere shouldn't leave the dashboard scoring by a ghost.
  useEffect(() => {
    if (scoringPattern && !patterns.some((p) => p.key === scoringPattern)) {
      setScoringPattern("");
    }
  }, [patterns, scoringPattern]);

  useEffect(() => {
    setBoardLoading(true);
    setBoardError(false);
    const params = new URLSearchParams({ limit: "100", sort });
    if (filter) params.set("category", filter);
    if (scoringPattern) params.set("pattern", scoringPattern);
    fetch(`/api/admissions?${params}`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => setBoard(d.items))
      .catch(() => { setBoard([]); setBoardError(true); })
      .finally(() => setBoardLoading(false));
  }, [filter, sort, scoringPattern]);

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
    const q = scoringPattern ? `?pattern=${encodeURIComponent(scoringPattern)}` : "";
    fetch(`/api/admissions/${selected.subject_id}/${selected.hadm_id}${q}`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setDetail)
      .catch(() => setDetailError(true));
  }, [selected, scoringPattern]);

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
          <a className={page === "dashboard" ? "active" : ""} onClick={() => setPage("dashboard")}>
            <Icon name="dashboard" /><span>Dashboard</span></a>
          <a className={page === "monitoring" ? "active" : ""} onClick={() => setPage("monitoring")}>
            <Icon name="monitor_heart" /><span>Patient Monitoring</span></a>
          <a className={page === "leadtime" ? "active" : ""} onClick={() => setPage("leadtime")}>
            <Icon name="schedule" /><span>Early Warning</span></a>
          <a className={page === "evaluation" ? "active" : ""} onClick={() => setPage("evaluation")}>
            <Icon name="fact_check" /><span>Detector Accuracy</span></a>
          <a className={page === "rules" ? "active" : ""} onClick={() => setPage("rules")}>
            <Icon name="menu_book" /><span>Scoring Rule Book</span></a>
          <a className={`navbuilder ${page === "builder" ? "active" : ""}`} onClick={() => setPage("builder")}>
            <Icon name="construction" /><span>Pattern Builder</span></a>
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

          {patterns.length > 0 && (
            <div className="sortwrap">
              <select className={`sort ${scoringPattern ? "patternon" : ""}`}
                value={scoringPattern} title={TIPS.scoringPattern}
                onChange={(e) => setScoringPattern(e.target.value)}>
                <option value="">Score by: all 8 labs (built-in)</option>
                {patterns.map((p) => (
                  <option key={p.key} value={p.key}>Score by: {p.name}</option>
                ))}
              </select>
            </div>
          )}

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
            <span className="title">
              {page === "monitoring" ? "Patient Monitoring"
                : page === "evaluation" ? "Detector Accuracy"
                : page === "leadtime" ? "Early Warning"
                : page === "rules" ? "Scoring Rule Book"
                : page === "builder" ? "Pattern Builder"
                : "Deterioration Watch"}
            </span>
          </div>
          <div className="actions">
            <div className="live"><span className="dot" />System Live</div>
            <Icon name="notifications" />
            <Icon name="apps" />
            <div className="avatar"><Icon name="person" /></div>
          </div>
        </header>

        <div className="canvas">
          {page === "evaluation" ? (
            <Evaluation />
          ) : page === "leadtime" ? (
            <LeadTime />
          ) : page === "rules" ? (
            <RuleBook />
          ) : page === "builder" ? (
            // A run result is only useful if you can go look at the patient it
            // found, so the builder can hand an admission back to Monitoring.
            <Builder onOpenPatient={(subject_id, hadm_id) => {
              setSelected({ subject_id, hadm_id });
              setPage("monitoring");
            }} />
          ) : (
            <>
              {detailError && <div className="placeholder err">Couldn't load this patient — is the API running?</div>}
              {!detail && !detailError && <div className="placeholder">Loading patient…</div>}
              {detail && (page === "monitoring"
                ? <Monitoring d={detail} meta={selected} />
                : <Detail d={detail} meta={selected} />)}
            </>
          )}
        </div>

        <footer className="databar">
          {stats ? <DataBar stats={stats} /> : <div className="seg">DB: MIMIC-III LABEVENTS</div>}
          <div className="seg">STATION: 4B-NC-01 · CLINICIAN: DR. SMITH</div>
        </footer>
      </main>

      {/* Floating dataset assistant (bottom-right) */}
      <Chatbot />
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

  // Early-warning lead time for this admission (concern = first Medium+, vs the
  // first critical value). Reference lines are placed on the trajectory below.
  const lt = d.lead_time || {};
  const concernLabel = lt.concern_time ? fmtTime(lt.concern_time) : null;
  const eventLabel = lt.event_time ? fmtTime(lt.event_time) : null;
  const fmtH = (h) => (h >= 48 ? `${(h / 24).toFixed(1)} days` : `${h} h`);
  const leadMsg = !lt.deteriorated
    ? "No critically out-of-range value was reached during this stay."
    : !lt.concerned
      ? `A critical ${lt.event_lab} value appeared without the score escalating first.`
      : lt.lead_concern_hours > 0
        ? `Risk flagged concern ${fmtH(lt.lead_concern_hours)} before the first critical value (${lt.event_lab}).`
        : `Risk escalated at the same measurement as the first critical value (${lt.event_lab}).`;

  // Header metric cluster — real per-admission summary (from the board row).
  const nHigh = meta?.n_high ?? (d.risk.contributions || []).filter((c) => c.status === "critical").length;
  const nWorse = meta?.n_worsening ?? (d.risk.contributions || []).filter((c) => c.trend === "worsening").length;
  const nLabs = meta?.n_measurements ?? d.labs.reduce((s, l) => s + l.points.length, 0);
  const span = meta?.span_hours;

  return (
    <>
      <ScoredBy risk={d.risk} />

      {/* Bento header: score card + metric cluster */}
      <section className="bento">
        <div className={`panel scorecard ${cat}`}>
          <Icon name="warning" className="ghost" />
          <div>
            <div className="eyebrow">
              {d.risk.pattern ? `Risk Index · ${d.risk.pattern_name}` : "Current Risk Index"}
            </div>
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
          {lt.deteriorated && (concernLabel || eventLabel) && (
            <div className="trajlegend">
              {concernLabel && <span className="lg concern"><span className="swatch" />First concern</span>}
              {eventLabel && <span className="lg event"><span className="swatch" />First critical value</span>}
            </div>
          )}
        </div>
        <div className="leadcallout"><Icon name="schedule" /><Tip text={TIPS.lead_time}>{leadMsg}</Tip></div>
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
              dot={false} activeDot={{ r: 5 }} />
            {concernLabel && (
              <ReferenceLine x={concernLabel} stroke="#f59e0b" strokeDasharray="3 3"
                label={{ value: "concern", position: "insideTopLeft", fill: "#f59e0b", fontSize: 10 }} />
            )}
            {eventLabel && eventLabel !== concernLabel && (
              <ReferenceLine x={eventLabel} stroke="#ef4444" strokeDasharray="3 3"
                label={{ value: "critical", position: "insideTopRight", fill: "#ef4444", fontSize: 10 }} />
            )}
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

/* Says out loud which rules produced the score on screen. Without this the
 * numbers silently mean two different things depending on the selector. */
function ScoredBy({ risk }) {
  if (!risk?.pattern) return null;
  return (
    <div className="scoredby">
      <Icon name="construction" />
      <span>
        Scored by your pattern <b>{risk.pattern_name}</b> — only its labs count,
        and only when they move the way the pattern says. Switch back to
        “all 8 labs” in the sidebar for the built-in score.
      </span>
    </div>
  );
}

// ── Patient Monitoring page: clinical-syndrome detection + live lab vitals ──
function Monitoring({ d, meta }) {
  const cat = d.risk.category;
  const byId = Object.fromEntries((d.risk.contributions || []).map((c) => [c.itemid, c]));
  const syndromes = d.syndromes || [];
  const nCritical = syndromes.filter((s) => s.severity === "critical").length;

  return (
    <>
      {/* Compact patient strip */}
      <section className={`panel monitorhead ${cat}`}>
        <div className="who">
          <Icon name="monitor_heart" className="ghost" />
          <div>
            <div className="eyebrow">Patient Monitoring</div>
            <h2>Patient {d.subject_id}</h2>
            <div className="adm">ADMISSION ID: {d.hadm_id}</div>
          </div>
        </div>
        <div className="summary">
          <div className="stat">
            <span className="num">{syndromes.length}</span>
            <span className="lbl">pattern{syndromes.length === 1 ? "" : "s"} detected</span>
          </div>
          <div className={`stat ${nCritical > 0 ? "crit" : ""}`}>
            <span className="num">{nCritical}</span>
            <span className="lbl">critical</span>
          </div>
          <div className="stat">
            <span className="badge" title={TIPS.category}>{cat} Risk</span>
            <span className="lbl">
              {d.risk.pattern
                ? `score ${d.risk.score} of ${d.risk.max_score}`
                : `overall score ${d.risk.score}`}
            </span>
          </div>
        </div>
      </section>

      <ScoredBy risk={d.risk} />

      {/* Clinical syndrome detection — the star of this page */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.syndromes}>Clinical Syndrome Detection</Tip></h3>
            <div className="desc">Named patterns found across several labs at once — more telling than any single value</div>
          </div>
        </div>
        {syndromes.length === 0 ? (
          <div className="placeholder small synempty">
            <Icon name="verified" />
            No syndromic patterns detected — this patient's labs don't match a known
            deterioration pattern.
          </div>
        ) : (
          <div className="syngrid">
            {syndromes.map((s) => <SyndromeCard key={s.key} s={s} />)}
          </div>
        )}
      </section>

      {/* Live lab vitals (reuses the dashboard's lab cards) */}
      <section className="panel labpanel">
        <div className="head">
          <h3><Tip text={TIPS.labTrends}>Live Lab Vitals ({d.labs.length} tests)</Tip></h3>
        </div>
        <div className="labgrid">
          {d.labs.map((lab) => <LabCard key={lab.itemid} lab={lab} info={byId[lab.itemid]} />)}
        </div>
      </section>
    </>
  );
}

function SyndromeCard({ s }) {
  const dirArrow = { high: "↑", low: "↓" };
  return (
    <div className={`syncard ${s.severity} ${s.custom ? "custom" : ""}`}>
      <div className="synhead">
        <div className="syntitle">
          <Icon name={s.custom ? "construction" : s.severity === "critical" ? "emergency" : "warning"} />
          <span className="name">{s.name}</span>
          {s.custom && (
            <span className="synbadge" title="Built in the Pattern Builder, not a built-in syndrome">
              Custom
            </span>
          )}
        </div>
      </div>
      <div className="synplain">{s.plain}</div>
      <div className="synsignals">
        {s.matched.map((m) => (
          <span key={m.itemid} className={`signal ${m.status}`}
            title={`${m.test_name} ${(+m.value).toPrecision(3) / 1} ${m.unit} — ${m.status}${m.trend === "worsening" ? ", worsening" : ""}`}>
            {GLOSSARY[m.test_name]
              ? <Tip text={GLOSSARY[m.test_name]}>{m.test_name}</Tip>
              : m.test_name}
            <span className="sv">{(+m.value).toPrecision(3) / 1}{dirArrow[m.direction] || ""}</span>
          </span>
        ))}
        {s.missing.map((m) => (
          <span key={m.itemid} className="signal absent"
            title={`${m.test_name} would also be expected (${m.direction}) but is in range`}>
            {m.test_name}<span className="sv">—</span>
          </span>
        ))}
        {(s.research_only || []).map((r) => (
          <span key={`ro-${r.name}-${r.direction}`} className="signal untested"
            title={`${r.name} (${r.direction}) is part of this pattern but isn't measured in this dataset, so it wasn't checked`}>
            {r.name}<span className="sv">n/a</span>
          </span>
        ))}
      </div>
      {(s.citations || []).length > 0 && (
        <div className="syncites">
          <Icon name="menu_book" />
          {s.citations.map((c, i) => (
            c.url
              ? <a key={i} href={c.url} target="_blank" rel="noreferrer" title={c.title || c.url}>
                  {c.title || c.url}
                </a>
              : <span key={i}>{c.title}</span>
          ))}
        </div>
      )}
      {s.worsening && (
        <div className="synfoot"><Icon name="trending_up" />Contributing labs are trending worse</div>
      )}
    </div>
  );
}

// ── Detector Accuracy page: our reference-range detector vs MIMIC's FLAG ──
function Evaluation() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/evaluation")
      .then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.detail || "error"); return j; }))
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="placeholder err">{error}</div>;
  if (!data) return <div className="placeholder">Computing accuracy…</div>;

  const o = data.overall;
  const CARDS = [
    ["Accuracy", o.accuracy, TIPS.eval_accuracy, "ok"],
    ["Precision", o.precision, TIPS.eval_precision, o.precision < 80 ? "warn" : "ok"],
    ["Recall", o.recall, TIPS.eval_recall, o.recall < 80 ? "warn" : "ok"],
    ["Specificity", o.specificity, TIPS.eval_specificity, "ok"],
    ["F1 Score", o.f1, TIPS.eval_f1, "ok"],
  ];
  const fmt = (n) => (+n).toLocaleString();

  return (
    <>
      <section className="panel section">
        <div className="head">
          <div>
            <h3>Detector Accuracy vs MIMIC FLAG</h3>
            <div className="desc">
              How our reference-range anomaly detector agrees with MIMIC's own
              “abnormal” flag, across {fmt(o.total)} lab values.
            </div>
          </div>
        </div>

        <div className="evalcards">
          {CARDS.map(([label, val, tip, tone]) => (
            <div key={label} className={`panel metric evalmetric ${tone}`}>
              <div className="label"><Tip text={tip}>{label}</Tip></div>
              <div className="val">{val}<span className="unit">%</span></div>
            </div>
          ))}
        </div>

        <div className="evalnote"><Icon name="info" />{data.note}</div>
      </section>

      {/* Overall confusion matrix */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.eval_cm}>Confusion Matrix</Tip></h3>
            <div className="desc">Every lab value bucketed by our call vs MIMIC's flag</div>
          </div>
        </div>
        <div className="cmatrix">
          <div className="cmcell tp"><span className="k">True Positive</span><span className="n">{fmt(o.tp)}</span><span className="d">flagged by both</span></div>
          <div className="cmcell fp"><span className="k">False Positive</span><span className="n">{fmt(o.fp)}</span><span className="d">we flagged, MIMIC didn't</span></div>
          <div className="cmcell fn"><span className="k">False Negative</span><span className="n">{fmt(o.fn)}</span><span className="d">MIMIC flagged, we missed</span></div>
          <div className="cmcell tn"><span className="k">True Negative</span><span className="n">{fmt(o.tn)}</span><span className="d">normal in both</span></div>
        </div>
      </section>

      {/* Per-lab breakdown */}
      <section className="panel factortable">
        <div className="head">
          <h3>Per-Lab Breakdown</h3>
          <div className="note"><Icon name="science" />Where the detector agrees — and where it over-flags</div>
        </div>
        <div className="tablewrap">
          <table className="factors">
            <thead>
              <tr>
                <th>Lab</th>
                <th className="r">Values</th>
                <th className="r"><Tip text={TIPS.eval_precision}>Precision</Tip></th>
                <th className="r"><Tip text={TIPS.eval_recall}>Recall</Tip></th>
                <th className="r"><Tip text={TIPS.eval_accuracy}>Accuracy</Tip></th>
                <th className="c">Agreement</th>
              </tr>
            </thead>
            <tbody>
              {data.per_lab.map((l) => (
                <tr key={l.itemid}>
                  <td className="name">
                    <span className="lead">
                      {GLOSSARY[l.test_name]
                        ? <Tip text={GLOSSARY[l.test_name]}>{l.test_name}</Tip>
                        : l.test_name}
                    </span>
                  </td>
                  <td className="val">{fmt(l.total)}</td>
                  <td className="val">{l.precision}%</td>
                  <td className="val">{l.recall}%</td>
                  <td className="val">{l.accuracy}%</td>
                  <td className="c">
                    <span className="agbar"><span className="fill" style={{ width: `${l.accuracy}%` }} /></span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

// ── Early Warning page: how far ahead the score escalates vs the first critical value ──
function LeadTime() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/lead-time")
      .then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.detail || "error"); return j; }))
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="placeholder err">{error}</div>;
  if (!data) return <div className="placeholder">Computing lead time…</div>;

  const fmt = (n) => (+n).toLocaleString();
  const BANDS = [
    ["First concern", "concern", TIPS.lt_concern, "warn"],
    ["High-risk alert", "alert", TIPS.lt_alert, "crit"],
  ];

  return (
    <>
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.lead_time}>Early-Warning Lead Time</Tip></h3>
            <div className="desc">
              Of {fmt(data.n_deteriorated)} admissions that reached a{" "}
              <Tip text={TIPS.lt_event}>critical lab value</Tip>, how many hours
              earlier our trend-aware risk score had already escalated.
            </div>
          </div>
        </div>

        <div className="leadbands">
          {BANDS.map(([label, key, tip, tone]) => {
            const b = data[key];
            return (
              <div key={key} className={`panel leadband ${tone}`}>
                <div className="eyebrow"><Tip text={tip}>{label}</Tip></div>
                <div className="leadbig">
                  {b.median_lead_hours != null ? b.median_lead_hours : "—"}
                  <span className="unit">h median lead</span>
                </div>
                <div className="leadsub">
                  <span><b>{b.early_warning_rate}%</b> warned early</span>
                  <span><Tip text={TIPS.lt_rate}>{fmt(b.n_early_warning)} admissions</Tip></span>
                </div>
                {b.median_lead_hours != null && (
                  <div className="leadsub muted">
                    <span>75th pct {b.p75_lead_hours} h</span>
                    <span>max {b.max_lead_hours} h</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="evalnote"><Icon name="info" />{data.note}</div>
      </section>

      <section className="panel section">
        <div className="head">
          <div>
            <h3>How to read this</h3>
            <div className="desc">Why "first concern" leads more often than "high-risk alert"</div>
          </div>
        </div>
        <div className="leadexplain">
          The risk score weights a critical value heavily, so a single critical
          result is often what first pushes a patient to <b>High</b> — meaning the
          high-risk alert tends to coincide with the deterioration event rather than
          precede it. The softer <b>first concern</b> threshold (the score leaving
          Low) is reached through accumulating abnormal and worsening trends, so it
          fires earlier. This gap is exactly the motivation for a learned risk model
          that can read the trend before any single value turns critical.
        </div>
      </section>
    </>
  );
}

// ── Scoring Rule Book: the transparent, cited logic behind every score ──
const WORSE_RULE = {
  high: { arrow: "↑", text: "Rising is dangerous" },
  low: { arrow: "↓", text: "Falling is dangerous" },
  both: { arrow: "↕", text: "Either direction is dangerous" },
};
const DIR_ARROW = { high: "↑ above range", low: "↓ below range" };

function RuleBook() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/rules")
      .then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.detail || "error"); return j; }))
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="placeholder err">{error}</div>;
  if (!data) return <div className="placeholder">Loading rule book…</div>;

  const src = data.sources;
  // A cited-source pill: links out when a URL exists, tooltip shows full citation.
  const Source = ({ id }) => {
    const s = src[id];
    if (!s) return null;
    const inner = (
      <span className={`rbsrc ${id === "engine" ? "engine" : ""}`}>
        <Icon name={s.url ? "menu_book" : "tune"} />{s.label}
      </span>
    );
    const body = <Tip text={s.citation}>{inner}</Tip>;
    return s.url
      ? <a className="rbsrclink" href={s.url} target="_blank" rel="noreferrer" title={TIPS.rb_source}>{body}</a>
      : body;
  };

  const used = Object.keys(src).filter((id) =>
    data.ranges.some((r) => r.range_source === id || r.clinical_source === id) ||
    data.syndromes.some((s) => s.source === id) ||
    data.scoring.steps.some((s) => s.source === id) ||
    data.classification.source === id);

  return (
    <>
      {/* Intro */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3>How every score is decided</h3>
            <div className="desc">
              This project is a transparent rule engine, not a black box. Every page
              here — the risk score, the alerts, the syndromes — is driven by the
              rules below. Each is tagged with the published source it's based on.
            </div>
          </div>
        </div>
        <div className="evalnote"><Icon name="info" />{data.disclaimer}</div>
      </section>

      {/* Reference ranges */}
      <section className="panel factortable">
        <div className="head">
          <h3><Tip text={TIPS.rb_ranges}>1 · Reference Ranges</Tip></h3>
          <div className="note"><Icon name="science" />The normal range for each lab</div>
        </div>
        <div className="tablewrap">
          <table className="factors">
            <thead>
              <tr>
                <th>Lab</th>
                <th className="r">Normal range</th>
                <th><Tip text={TIPS.rb_worsening}>Worsening direction</Tip></th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {data.ranges.map((r) => {
                const w = WORSE_RULE[r.worsening] || WORSE_RULE.both;
                return (
                  <tr key={r.itemid}>
                    <td className="name">
                      <span className="lead">
                        {GLOSSARY[r.name] ? <Tip text={GLOSSARY[r.name]}>{r.name}</Tip> : r.name}
                      </span>
                    </td>
                    <td className="val">{r.normal_low}–{r.normal_high}<span className="unit">{r.unit}</span></td>
                    <td>
                      <span className="rbdir"><span className="arr">{w.arrow}</span>{w.text}</span>
                    </td>
                    <td><div className="rbsrcs"><Source id={r.range_source} /><Source id={r.clinical_source} /></div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Classification → points */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.rb_classification}>2 · Classifying a value</Tip></h3>
            <div className="desc">{data.classification.rule}</div>
          </div>
          <Source id={data.classification.source} />
        </div>
        <div className="rbbands">
          {data.classification.bands.map((b) => (
            <div key={b.status} className={`rbband ${b.status}`}>
              <div className="rbhead">
                <span className={`statuspill ${b.status}`}>{b.label}</span>
                <span className="rbpts">+{b.points}<span className="u">pts</span></span>
              </div>
              <div className="rbtest">{b.test}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Scoring math */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.rb_scoring}>3 · Building the score</Tip></h3>
            <div className="desc">
              How each lab's status and trend add up. Trend uses a {data.scoring.trend_window}-point window.
            </div>
          </div>
        </div>
        <ol className="rbsteps">
          {data.scoring.steps.map((s, i) => (
            <li key={i}>
              <span className="rbstepn">{i + 1}</span>
              <div className="rbstepbody">
                <div className="rbsteptop"><b>{s.name}</b><Source id={s.source} /></div>
                <div className="rbstepd">{s.detail}</div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Risk categories */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.rb_categories}>4 · Risk categories</Tip></h3>
            <div className="desc">The total score maps to a triage category.</div>
          </div>
        </div>
        <div className="rbcats">
          {data.categories.map((c) => (
            <div key={c.category} className={`rbcat ${c.category}`}>
              <span className={`chip ${c.category}`}>{c.category}</span>
              <div className="rbrange">
                {c.max == null ? `${c.min}+` : c.min === c.max ? `${c.min}` : `${c.min}–${c.max}`}
                <span className="u">pts</span>
              </div>
              <div className="rbmeaning">{c.meaning}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Syndromes */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3><Tip text={TIPS.rb_syndromes}>5 · Clinical syndromes</Tip></h3>
            <div className="desc">
              Named patterns that fire when enough signal labs move together.
            </div>
          </div>
        </div>
        <div className="rbsyngrid">
          {data.syndromes.map((s) => (
            <div key={s.key} className="rbsyn">
              <div className="rbsynhead">
                <span className="name">{s.name}</span>
                <Source id={s.source} />
              </div>
              <div className="rbsynplain">{s.plain}</div>
              <div className="rbsynsignals">
                {s.signals.map((sig) => (
                  <span key={sig.itemid} className="rbsig">
                    {GLOSSARY[sig.name] ? <Tip text={GLOSSARY[sig.name]}>{sig.name}</Tip> : sig.name}
                    <span className="d">{DIR_ARROW[sig.direction]}</span>
                  </span>
                ))}
              </div>
              <div className="rbsynfoot">
                <Icon name="rule" />Fires when ≥ {s.min_signals} of {s.signals.length} present
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Sources */}
      <section className="panel section">
        <div className="head">
          <div>
            <h3>Sources</h3>
            <div className="desc">The published references behind the rules above.</div>
          </div>
        </div>
        <ul className="rbsources">
          {used.map((id) => {
            const s = src[id];
            return (
              <li key={id}>
                <span className="rblabel">{s.label}</span>
                <span className="rbcite">{s.citation}</span>
                {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="rbopen">
                  <Icon name="open_in_new" />Open</a>}
              </li>
            );
          })}
        </ul>
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
              dot={false} activeDot={{ r: 4 }} />
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
