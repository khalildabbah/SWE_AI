import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceArea, Area, AreaChart, CartesianGrid,
} from "recharts";

const RISK_COLOR = { Low: "#2ea043", Medium: "#d29922", High: "#f85149" };
const fmtTime = (iso) => iso.replace("T", " ").slice(0, 16);

export default function App() {
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState("High");
  const [board, setBoard] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);

  useEffect(() => { fetch("/api/stats").then((r) => r.json()).then(setStats); }, []);

  useEffect(() => {
    const q = filter ? `?category=${filter}&limit=100` : "?limit=100";
    fetch(`/api/admissions${q}`).then((r) => r.json()).then((d) => setBoard(d.items));
  }, [filter]);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    fetch(`/api/admissions/${selected.subject_id}/${selected.hadm_id}`)
      .then((r) => r.json()).then(setDetail);
  }, [selected]);

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
              onClick={() => setFilter(c)}>{c || "All"}</button>
          ))}
        </div>
        <div className="list">
          {board.map((a) => (
            <div key={`${a.subject_id}-${a.hadm_id}`}
              className={`row ${selected && selected.hadm_id === a.hadm_id ? "sel" : ""}`}
              onClick={() => setSelected(a)}>
              <div>
                <div className="pid">Patient {a.subject_id}</div>
                <div className="meta">
                  Adm {a.hadm_id} · {a.n_measurements} labs · {a.span_hours}h ·
                  {" "}{a.n_high} critical · {a.n_worsening} worsening
                </div>
              </div>
              <span className={`badge ${a.category}`}>{a.category} · {a.score}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="detail">
        {!detail && <div className="placeholder">Select a patient to view trends, risk & alerts</div>}
        {detail && <Detail d={detail} />}
      </div>
    </div>
  );
}

function StatsBar({ stats }) {
  const p = stats.pipeline;
  return (
    <div className="stats">
      <Stat n={(+p.raw_rows).toLocaleString()} l="rows ingested" />
      <Stat n={(+p.kept_rows).toLocaleString()} l="clean values" />
      <Stat n={(+p.patients).toLocaleString()} l="patients" />
      <Stat n={`${p.build_seconds}s`} l="pipeline time" />
    </div>
  );
}
const Stat = ({ n, l }) => (
  <div className="stat"><div className="n">{n}</div><div className="l">{l}</div></div>
);

function Detail({ d }) {
  const traj = d.trajectory.map((t) => ({ ...t, label: fmtTime(t.time) }));
  return (
    <>
      <div className="card">
        <h2>Patient {d.subject_id} · Admission {d.hadm_id}</h2>
        <div className="riskhead">
          <div className="big" style={{ color: RISK_COLOR[d.risk.category] }}>
            {d.risk.score}
          </div>
          <span className={`badge ${d.risk.category}`}>{d.risk.category} RISK</span>
        </div>
      </div>

      <div className="card">
        <h2>Risk trajectory over time</h2>
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
        <h2>Early-warning alerts</h2>
        {d.alerts.length === 0 && <div className="placeholder" style={{ marginTop: 0 }}>No alerts</div>}
        {d.alerts.map((a, i) => (
          <div key={i} className={`alert ${a.level}`}>
            <span className={`dot ${a.level}`} />{a.message}
          </div>
        ))}
      </div>

      <div className="card">
        <h2>Lab trends ({d.labs.length} tests)</h2>
        <div className="labgrid">
          {d.labs.map((lab) => <LabChart key={lab.itemid} lab={lab} />)}
        </div>
      </div>
    </>
  );
}

function LabChart({ lab }) {
  const data = lab.points.map((p) => ({ label: fmtTime(p.time), value: p.value }));
  return (
    <div className="lab">
      <div className="t">{lab.test_name} ({lab.unit})</div>
      <ResponsiveContainer width="100%" height={130}>
        <LineChart data={data}>
          <ReferenceArea y1={lab.normal_low} y2={lab.normal_high} fill="#2ea043" fillOpacity={0.12} />
          <XAxis dataKey="label" hide />
          <YAxis tick={{ fontSize: 9, fill: "#8b98a5" }} width={32} domain={["auto", "auto"]} />
          <Tooltip contentStyle={{ background: "#1a2129", border: "1px solid #2a3540", fontSize: 12 }} />
          <Line type="monotone" dataKey="value" stroke="#58a6ff" strokeWidth={1.5} dot={{ r: 1.5 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
