import React, { useEffect, useRef, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceArea,
} from "recharts";

// Floating dataset assistant. Talks to POST /api/chat, which proxies Gemini
// server-side (the API key never reaches the browser) and answers ONLY questions
// about this deterioration dataset. Charts returned by the agent render inline.

const Icon = ({ name, className = "" }) => (
  <span className={`material-symbols-outlined ${className}`}>{name}</span>
);

const SUGGESTIONS = [
  "Which patients are at the highest risk right now?",
  "Show me the lab trends for the top high-risk patient",
  "What does the risk score mean, and which labs are tracked?",
];

const fmtTime = (iso) => (iso || "").replace("T", " ").slice(0, 16);

// One inline lab chart (mirrors the dashboard's LabCard styling).
function ChatChart({ chart }) {
  const data = (chart.points || []).map((p) => ({ label: fmtTime(p.time), value: p.value }));
  return (
    <div className="cbchart">
      <div className="cbchart-title">{chart.title}</div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 8, right: 6, left: 0, bottom: 0 }}>
          <ReferenceArea y1={chart.normal_low} y2={chart.normal_high} fill="#10b981" fillOpacity={0.1} />
          <XAxis dataKey="label" hide />
          <YAxis tick={{ fontSize: 9, fill: "#8c909f", fontFamily: "Geist Mono" }} width={30} domain={["auto", "auto"]} />
          <Tooltip contentStyle={{ background: "#1c2b3c", border: "1px solid #424754", borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: "#c2c6d6" }} />
          <Line type="monotone" dataKey="value" stroke="#adc6ff" strokeWidth={1.6} dot={false} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
      <div className="cbchart-foot">
        Green band = normal range{chart.unit ? ` (${chart.normal_low}–${chart.normal_high} ${chart.unit})` : ""}
      </div>
    </div>
  );
}

// Lightweight markdown-ish renderer: paragraphs, "- " bullets, and **bold**.
function renderText(text) {
  const lines = (text || "").split("\n");
  const blocks = [];
  let bullets = [];
  const flush = () => {
    if (bullets.length) { blocks.push(<ul key={`u${blocks.length}`}>{bullets}</ul>); bullets = []; }
  };
  const inline = (s) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((seg, i) =>
      seg.startsWith("**") && seg.endsWith("**")
        ? <strong key={i}>{seg.slice(2, -2)}</strong> : <span key={i}>{seg}</span>);
  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    if (/^\s*[-*]\s+/.test(line)) {
      bullets.push(<li key={`l${i}`}>{inline(line.replace(/^\s*[-*]\s+/, ""))}</li>);
    } else if (line.trim() === "") {
      flush();
    } else {
      flush();
      blocks.push(<p key={`p${i}`}>{inline(line)}</p>);
    }
  });
  flush();
  return blocks;
}

export default function Chatbot() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]); // {role:'user'|'model', text, charts?}
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages, loading, open]);

  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus();
  }, [open]);

  async function send(text) {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    setInput("");
    const history = messages.map((m) => ({ role: m.role, text: m.text }));
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setLoading(true);
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, history }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setMessages((m) => [...m, {
          role: "model",
          text: data.detail || "Something went wrong reaching the assistant. Please try again.",
        }]);
      } else {
        setMessages((m) => [...m, { role: "model", text: data.reply, charts: data.charts || [] }]);
      }
    } catch {
      setMessages((m) => [...m, { role: "model", text: "Couldn't reach the assistant — is the API running?" }]);
    } finally {
      setLoading(false);
    }
  }

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <>
      <button className={`cbfab ${open ? "hidden" : ""}`} onClick={() => setOpen(true)}
        title="Ask about the dataset" aria-label="Open assistant">
        <Icon name="forum" />
      </button>

      <div className={`cbpanel ${open ? "open" : ""}`} role="dialog" aria-label="Dataset assistant">
        <header className="cbhead">
          <div className="cbtitle">
            <span className="cbavatar"><Icon name="smart_toy" /></span>
            <div>
              <div className="cbname">Dataset Assistant</div>
              <div className="cbsub">Answers from this dataset only</div>
            </div>
          </div>
          <button className="cbclose" onClick={() => setOpen(false)} aria-label="Close"><Icon name="close" /></button>
        </header>

        <div className="cbbody" ref={bodyRef}>
          {messages.length === 0 && (
            <div className="cbwelcome">
              <p>Hi! I can answer questions about the patients, labs, risk scores and
                alerts in this system — and show graphs. Try one of these:</p>
              <div className="cbsuggest">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)} disabled={loading}>{s}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`cbmsg ${m.role}`}>
              {m.role === "model" && <span className="cbmavatar"><Icon name="smart_toy" /></span>}
              <div className="cbbubble">
                <div className="cbtext">{renderText(m.text)}</div>
                {(m.charts || []).map((c, j) => <ChatChart key={j} chart={c} />)}
              </div>
            </div>
          ))}

          {loading && (
            <div className="cbmsg model">
              <span className="cbmavatar"><Icon name="smart_toy" /></span>
              <div className="cbbubble"><div className="cbtyping"><span /><span /><span /></div></div>
            </div>
          )}
        </div>

        <div className="cbinput">
          <textarea ref={inputRef} rows={1} value={input} placeholder="Ask about a patient, lab, or risk…"
            onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} disabled={loading} />
          <button onClick={() => send()} disabled={loading || !input.trim()} aria-label="Send">
            <Icon name="send" />
          </button>
        </div>
      </div>
    </>
  );
}
