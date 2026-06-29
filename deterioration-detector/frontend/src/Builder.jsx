import React, { useEffect, useRef, useState } from "react";

/*
 * SYNDROME BUILDER ("build it yourself")
 * --------------------------------------
 * Name a candidate syndrome, then co-work with an AI that searches the
 * literature to agree on CITED pattern rules over the 8 tracked labs. Save the
 * rule set and immediately try it on real patient data to see who matches.
 *
 * Talks to /api/builder/* — the OpenAI key (and live web search) stay
 * server-side. A rule is one lab + a direction (high/low) + a rationale + a
 * citation, mirroring the built-in syndrome shape.
 */

const Icon = ({ name, className = "" }) => (
  <span className={`material-symbols-outlined ${className}`}>{name}</span>
);

const SUGGESTIONS = [
  "What lab patterns point to hepatorenal syndrome?",
  "Which of our 8 labs suggest tumor lysis syndrome?",
  "Build rules for refeeding syndrome from these labs.",
];

// Minimal markdown-ish renderer (paragraphs, "- " bullets, **bold**).
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

const dirLabel = (d) => (d === "high" ? "↑ High" : "↓ Low");

export default function Builder() {
  const [labs, setLabs] = useState([]);
  const [saved, setSaved] = useState([]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [currentKey, setCurrentKey] = useState(null);

  const [rules, setRules] = useState([]); // {itemid,name,direction,rationale,citation}
  const [minSignals, setMinSignals] = useState(1);

  // co-work chat
  const [messages, setMessages] = useState([]); // {role, text, proposals?, citations?}
  const [input, setInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const bodyRef = useRef(null);

  // manual add + actions
  const [pickLab, setPickLab] = useState("");
  const [pickDir, setPickDir] = useState("high");
  const [saveMsg, setSaveMsg] = useState(null);
  const [run, setRun] = useState(null);
  const [runLoading, setRunLoading] = useState(false);

  useEffect(() => {
    fetch("/api/builder/labs").then((r) => r.json()).then((d) => {
      setLabs(d.labs || []);
      if (d.labs?.length) setPickLab(String(d.labs[0].itemid));
    }).catch(() => {});
    loadSaved();
  }, []);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages, chatLoading]);

  // keep min_signals within [1, rules.length]
  useEffect(() => {
    setMinSignals((m) => Math.max(1, Math.min(m, Math.max(1, rules.length))));
  }, [rules.length]);

  function loadSaved() {
    fetch("/api/builder/syndromes").then((r) => r.json())
      .then((d) => setSaved(d.items || [])).catch(() => {});
  }

  const labById = Object.fromEntries(labs.map((l) => [l.itemid, l]));
  const hasRule = (itemid, direction) =>
    rules.some((r) => r.itemid === itemid && r.direction === direction);

  function addRule(rule) {
    if (hasRule(rule.itemid, rule.direction)) return;
    setRules((rs) => [...rs, {
      itemid: rule.itemid,
      name: rule.name || labById[rule.itemid]?.name || `Lab ${rule.itemid}`,
      direction: rule.direction,
      rationale: rule.rationale || "",
      citation: rule.citation || { title: "", url: "" },
    }]);
    setRun(null);
  }

  function removeRule(itemid, direction) {
    setRules((rs) => rs.filter((r) => !(r.itemid === itemid && r.direction === direction)));
    setRun(null);
  }

  function addManual() {
    const itemid = Number(pickLab);
    if (!itemid) return;
    addRule({ itemid, direction: pickDir, name: labById[itemid]?.name });
  }

  async function send(text) {
    const msg = (text ?? input).trim();
    if (!msg || chatLoading) return;
    setInput("");
    const history = messages.map((m) => ({ role: m.role, text: m.text }));
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setChatLoading(true);
    try {
      const r = await fetch("/api/builder/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, message: msg, history }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setMessages((m) => [...m, { role: "model", text: data.detail || "The builder AI hit an error. Please try again." }]);
      } else {
        setMessages((m) => [...m, {
          role: "model", text: data.reply,
          proposals: data.proposals || [], citations: data.citations || [],
        }]);
      }
    } catch {
      setMessages((m) => [...m, { role: "model", text: "Couldn't reach the builder AI — is the API running?" }]);
    } finally {
      setChatLoading(false);
    }
  }

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  async function saveSyndrome() {
    setSaveMsg(null);
    try {
      const r = await fetch("/api/builder/syndromes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name, description, signals: rules, min_signals: minSignals, key: currentKey,
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setSaveMsg({ ok: false, text: data.detail || "Could not save." }); return; }
      setCurrentKey(data.key);
      setSaveMsg({ ok: true, text: `Saved “${data.name}”.` });
      loadSaved();
    } catch {
      setSaveMsg({ ok: false, text: "Couldn't reach the API." });
    }
  }

  function loadSyndrome(s) {
    setName(s.name);
    setDescription(s.description || "");
    setCurrentKey(s.key);
    setRules((s.signals || []).map((sg) => ({
      itemid: sg.itemid, name: sg.name, direction: sg.direction,
      rationale: sg.rationale || "", citation: sg.citation || { title: "", url: "" },
    })));
    setMinSignals(s.min_signals || 1);
    setRun(null);
    setSaveMsg(null);
  }

  async function deleteSyndrome(key, e) {
    e.stopPropagation();
    if (!window.confirm("Delete this saved syndrome?")) return;
    await fetch(`/api/builder/syndromes/${key}`, { method: "DELETE" }).catch(() => {});
    if (key === currentKey) setCurrentKey(null);
    loadSaved();
  }

  function newSyndrome() {
    setName(""); setDescription(""); setCurrentKey(null);
    setRules([]); setMinSignals(1); setRun(null); setSaveMsg(null); setMessages([]);
  }

  async function runOnData() {
    if (!rules.length) return;
    setRunLoading(true); setRun(null);
    try {
      const r = await fetch("/api/builder/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signals: rules, min_signals: minSignals }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) setRun({ error: data.detail || "Run failed." });
      else setRun(data);
    } catch {
      setRun({ error: "Couldn't reach the API." });
    } finally {
      setRunLoading(false);
    }
  }

  return (
    <div className="bld">
      <div className="bldintro">
        <h2><Icon name="construction" /> Syndrome Builder</h2>
        <p>Name a candidate syndrome, then research it with the AI co-pilot (it searches
          real literature). Agree on cited pattern rules over the 8 tracked labs, save them,
          and try the rule set on real patient data. Educational prototype — not medical advice.</p>
      </div>

      <div className="bldgrid">
        {/* ── Left: identity + co-work research chat ── */}
        <section className="bldcol">
          <div className="bldcard">
            <div className="bldfield">
              <label>Syndrome name</label>
              <input value={name} onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Hepatorenal Syndrome" />
            </div>
            <div className="bldfield">
              <label>Working description <span className="bldopt">(optional)</span></label>
              <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="What is this syndrome, and what are you trying to capture?" />
            </div>
          </div>

          <div className="bldcard bldchat">
            <div className="bldchat-head">
              <span className="bldavatar"><Icon name="smart_toy" /></span>
              <div>
                <div className="bldname">Research co-pilot</div>
                <div className="bldsub"><Icon name="travel_explore" /> Searches the web for cited rules</div>
              </div>
            </div>

            <div className="bldchat-body" ref={bodyRef}>
              {messages.length === 0 && (
                <div className="bldwelcome">
                  <p>Tell me the syndrome you want to build. I'll look up the evidence and
                    propose lab-based pattern rules you can accept into your rule set.</p>
                  <div className="bldsuggest">
                    {SUGGESTIONS.map((s) => (
                      <button key={s} onClick={() => send(s)} disabled={chatLoading}>{s}</button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m, i) => (
                <div key={i} className={`bldmsg ${m.role}`}>
                  {m.role === "model" && <span className="bldmavatar"><Icon name="smart_toy" /></span>}
                  <div className="bldbubble">
                    <div className="bldtext">{renderText(m.text)}</div>

                    {(m.proposals || []).length > 0 && (
                      <div className="bldprops">
                        <div className="bldprops-h">Proposed rules</div>
                        {m.proposals.map((p, j) => {
                          const added = hasRule(p.itemid, p.direction);
                          return (
                            <div key={j} className="bldprop">
                              <div className="bldprop-main">
                                <span className={`bldpill ${p.direction}`}>{p.name} {dirLabel(p.direction)}</span>
                                <button className="bldadd" disabled={added} onClick={() => addRule(p)}>
                                  <Icon name={added ? "check" : "add"} />{added ? "Added" : "Add"}
                                </button>
                              </div>
                              {p.rationale && <div className="bldprop-rat">{p.rationale}</div>}
                              {p.citation?.url
                                ? <a className="bldcite" href={p.citation.url} target="_blank" rel="noreferrer">
                                    <Icon name="link" />{p.citation.title || p.citation.url}</a>
                                : p.citation?.title && <div className="bldcite nolink"><Icon name="menu_book" />{p.citation.title}</div>}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {(m.citations || []).length > 0 && (
                      <div className="bldsources">
                        <span>Sources found:</span>
                        {m.citations.slice(0, 6).map((c, j) => (
                          <a key={j} href={c.url} target="_blank" rel="noreferrer" title={c.title}>[{j + 1}]</a>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {chatLoading && (
                <div className="bldmsg model">
                  <span className="bldmavatar"><Icon name="smart_toy" /></span>
                  <div className="bldbubble"><div className="bldtyping"><span /><span /><span /></div></div>
                </div>
              )}
            </div>

            <div className="bldchat-input">
              <textarea rows={1} value={input} placeholder="Ask the co-pilot to research a syndrome…"
                onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} disabled={chatLoading} />
              <button onClick={() => send()} disabled={chatLoading || !input.trim()} aria-label="Send">
                <Icon name="send" />
              </button>
            </div>
          </div>
        </section>

        {/* ── Right: the rule set being built ── */}
        <section className="bldcol">
          <div className="bldcard">
            <div className="bldcard-head">
              <h3>Pattern rules{name ? <> — <span className="bldhl">{name}</span></> : ""}</h3>
              <button className="bldghost" onClick={newSyndrome} title="Start a new syndrome">
                <Icon name="restart_alt" />New
              </button>
            </div>

            {rules.length === 0 ? (
              <div className="bldempty">No rules yet. Accept the co-pilot's proposals, or add one manually below.</div>
            ) : (
              <ul className="bldrules">
                {rules.map((r) => (
                  <li key={`${r.itemid}-${r.direction}`} className="bldrule">
                    <span className={`bldpill ${r.direction}`}>{r.name} {dirLabel(r.direction)}</span>
                    <div className="bldrule-body">
                      {r.rationale && <div className="bldrule-rat">{r.rationale}</div>}
                      {r.citation?.url
                        ? <a className="bldcite" href={r.citation.url} target="_blank" rel="noreferrer">
                            <Icon name="link" />{r.citation.title || r.citation.url}</a>
                        : r.citation?.title && <div className="bldcite nolink"><Icon name="menu_book" />{r.citation.title}</div>}
                    </div>
                    <button className="bldrm" onClick={() => removeRule(r.itemid, r.direction)} aria-label="Remove rule">
                      <Icon name="close" />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="bldmanual">
              <select value={pickLab} onChange={(e) => setPickLab(e.target.value)}>
                {labs.map((l) => <option key={l.itemid} value={l.itemid}>{l.name} ({l.unit})</option>)}
              </select>
              <select value={pickDir} onChange={(e) => setPickDir(e.target.value)}>
                <option value="high">↑ High</option>
                <option value="low">↓ Low</option>
              </select>
              <button className="bldghost" onClick={addManual}><Icon name="add" />Add rule</button>
            </div>

            {rules.length > 0 && (
              <div className="bldthresh">
                <label>Fires when at least</label>
                <select value={minSignals} onChange={(e) => setMinSignals(Number(e.target.value))}>
                  {Array.from({ length: rules.length }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
                <label>of {rules.length} rule{rules.length > 1 ? "s" : ""} match.</label>
              </div>
            )}

            <div className="bldactions">
              <button className="bldprimary" onClick={saveSyndrome} disabled={!name.trim() || !rules.length}>
                <Icon name="save" />{currentKey ? "Update" : "Save"} syndrome
              </button>
              <button className="bldsecondary" onClick={runOnData} disabled={!rules.length || runLoading}>
                <Icon name="science" />{runLoading ? "Running…" : "Run on patient data"}
              </button>
            </div>
            {saveMsg && <div className={`bldnote ${saveMsg.ok ? "ok" : "err"}`}>{saveMsg.text}</div>}
          </div>

          {run && (
            <div className="bldcard">
              <h3>Patient-data results</h3>
              {run.error ? (
                <div className="bldnote err">{run.error}</div>
              ) : (
                <>
                  <div className="bldstats">
                    <div className="bldstat"><b>{run.n_matched}</b><span>admissions match</span></div>
                    <div className="bldstat"><b>{run.match_rate}%</b><span>of {run.total_admissions}</span></div>
                    <div className="bldstat"><b>≥ {run.min_signals}</b><span>of {run.n_rules} rules</span></div>
                  </div>
                  {run.examples?.length > 0 ? (
                    <table className="bldtable">
                      <thead><tr><th>Patient</th><th>Admission</th><th>Matched labs</th></tr></thead>
                      <tbody>
                        {run.examples.map((m) => (
                          <tr key={`${m.subject_id}-${m.hadm_id}`}>
                            <td>{m.subject_id}</td>
                            <td>{m.hadm_id}</td>
                            <td>{m.matched.map((h) => (
                              <span key={h.itemid} className={`bldtag ${h.direction}`}>
                                {h.name} {h.value}
                              </span>
                            ))}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : <div className="bldempty">No admissions matched this rule set.</div>}
                  {run.n_matched > (run.examples?.length || 0) && (
                    <div className="bldhint">Showing the top {run.examples.length} of {run.n_matched} matches.</div>
                  )}
                </>
              )}
            </div>
          )}

          {saved.length > 0 && (
            <div className="bldcard">
              <h3>Saved syndromes</h3>
              <ul className="bldsaved">
                {saved.map((s) => (
                  <li key={s.key} className={s.key === currentKey ? "active" : ""} onClick={() => loadSyndrome(s)}>
                    <div>
                      <div className="bldsaved-name">{s.name}</div>
                      <div className="bldsaved-meta">{s.signals.length} rule{s.signals.length !== 1 ? "s" : ""} · fires at ≥ {s.min_signals}</div>
                    </div>
                    <button className="bldrm" onClick={(e) => deleteSyndrome(s.key, e)} aria-label="Delete"><Icon name="delete" /></button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
