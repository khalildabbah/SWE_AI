import React, { useEffect, useMemo, useRef, useState } from "react";

/*
 * PATTERN BUILDER ("build it yourself")
 * -------------------------------------
 * A guided, 3-step flow. Each step has its own focus:
 *   1. Choose the syndrome  — name (and describe) the candidate syndrome.
 *   2. Co-research with AI   — agree, in chat, on evidence-based pattern rules.
 *                              The co-pilot searches real literature and brings
 *                              the evidence INTO the chat (inline synopses) so
 *                              you rarely need to leave the page.
 *   3. Chosen patterns       — review/edit the rule set, save it, and try it on
 *                              real patient data.
 *
 * Talks to /api/builder/* — the OpenAI key (and live web search) stay
 * server-side. A pattern rule is one lab + a direction (high/low) + a rationale
 * + inline evidence + a citation.
 */

const Icon = ({ name, className = "" }) => (
  <span className={`material-symbols-outlined ${className}`}>{name}</span>
);

const STEPS = [
  { n: 1, label: "Choose syndrome", icon: "label" },
  { n: 2, label: "Co-research", icon: "travel_explore" },
  { n: 3, label: "Chosen patterns", icon: "checklist" },
];

const EXAMPLES = [
  "Hepatorenal Syndrome", "Tumor Lysis Syndrome",
  "Refeeding Syndrome", "Diabetic Ketoacidosis",
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

function Citation({ citation }) {
  if (citation?.url)
    return <a className="bldcite" href={citation.url} target="_blank" rel="noreferrer">
      <Icon name="link" />{citation.title || citation.url}</a>;
  if (citation?.title)
    return <div className="bldcite nolink"><Icon name="menu_book" />{citation.title}</div>;
  return null;
}

export default function Builder() {
  const [step, setStep] = useState(1);

  const [catalog, setCatalog] = useState([]); // {itemid,label,category,units,testable,n_rows}
  const [saved, setSaved] = useState([]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [currentKey, setCurrentKey] = useState(null);

  const [rules, setRules] = useState([]); // {itemid,name,direction,rationale,evidence,citation}
  const [minSignals, setMinSignals] = useState(1);

  // co-work chat
  const [messages, setMessages] = useState([]); // {role,text,proposals?,citations?}
  const [input, setInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const bodyRef = useRef(null);
  const kickedOff = useRef(false);

  // manual add (lab pick-list) + actions
  const [pickQuery, setPickQuery] = useState("");
  const [picked, setPicked] = useState(null);   // chosen catalog lab
  const [pickOpen, setPickOpen] = useState(false);
  const [pickDir, setPickDir] = useState("high");
  const [saveMsg, setSaveMsg] = useState(null);
  const [run, setRun] = useState(null);
  const [runLoading, setRunLoading] = useState(false);

  useEffect(() => {
    fetch("/api/builder/catalog").then((r) => r.json()).then((d) => {
      if (d.labs && d.labs.length) { setCatalog(d.labs); return; }
      // fall back to the tracked 8 if the catalog export isn't present
      fetch("/api/builder/labs").then((r) => r.json()).then((x) =>
        setCatalog((x.labs || []).map((l) => ({
          itemid: l.itemid, label: l.name, category: "Tracked",
          units: l.unit, n_rows: 0, testable: true,
        }))));
    }).catch(() => {});
    loadSaved();
  }, []);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages, chatLoading, step]);

  useEffect(() => {
    setMinSignals((m) => Math.max(1, Math.min(m, Math.max(1, rules.length))));
  }, [rules.length]);

  // Entering co-research for the first time kicks off the conversation so the
  // step is immediately productive about the chosen syndrome.
  useEffect(() => {
    if (step === 2 && !kickedOff.current && messages.length === 0 && name.trim()) {
      kickedOff.current = true;
      send(`Let's build lab-based pattern rules for "${name.trim()}". Search the `
        + `literature and propose pattern rules (a lab + a direction) — summarise the `
        + `key evidence here so I can decide without leaving the page.`);
    }
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  function loadSaved() {
    fetch("/api/builder/syndromes").then((r) => r.json())
      .then((d) => setSaved(d.items || [])).catch(() => {});
  }

  // testable (tracked) labs, keyed by lowercased label, for resolving names
  const testableByName = useMemo(() => Object.fromEntries(
    catalog.filter((l) => l.testable).map((l) => [l.label.toLowerCase(), l])), [catalog]);
  // identity tolerant of research-only labs (itemid is null): fall back to name
  const ruleKey = (r) =>
    `${r.itemid != null ? `id:${r.itemid}` : `nm:${(r.name || "").toLowerCase()}`}-${r.direction}`;
  const hasRule = (rule) => rules.some((r) => ruleKey(r) === ruleKey(rule));

  function addRule(rule) {
    if (hasRule(rule)) return;
    // resolve dataset membership locally when the caller didn't specify it
    const known = rule.itemid != null ? null : testableByName[(rule.name || "").toLowerCase()];
    setRules((rs) => [...rs, {
      itemid: rule.itemid != null ? rule.itemid : (known ? known.itemid : null),
      name: rule.name || (known ? known.label : ""),
      direction: rule.direction,
      in_dataset: rule.in_dataset != null ? rule.in_dataset : (rule.itemid != null || !!known),
      rationale: rule.rationale || "",
      evidence: rule.evidence || "",
      citation: rule.citation || { title: "", url: "" },
    }]);
    setRun(null);
  }

  function removeRule(rule) {
    setRules((rs) => rs.filter((r) => ruleKey(r) !== ruleKey(rule)));
    setRun(null);
  }

  // matches for the lab pick-list (label or category contains the query)
  const pickMatches = useMemo(() => {
    const s = pickQuery.trim().toLowerCase();
    const list = s
      ? catalog.filter((l) => l.label.toLowerCase().includes(s) || l.category.toLowerCase().includes(s))
      : catalog;
    return list.slice(0, 40);
  }, [pickQuery, catalog]);

  function choosePick(l) {
    setPicked(l); setPickQuery(l.label); setPickOpen(false);
  }

  function addManual() {
    // a clicked catalog lab, else an exact-label match on what was typed
    const lab = (picked && picked.label.toLowerCase() === pickQuery.trim().toLowerCase())
      ? picked
      : catalog.find((l) => l.label.toLowerCase() === pickQuery.trim().toLowerCase());
    if (lab) {
      addRule({ itemid: lab.testable ? lab.itemid : null, name: lab.label,
                direction: pickDir, in_dataset: lab.testable });
    } else {
      const typed = pickQuery.trim();
      if (!typed) return;
      addRule({ itemid: null, name: typed, direction: pickDir, in_dataset: false });
    }
    setPickQuery(""); setPicked(null); setPickOpen(false);
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
      itemid: sg.itemid != null ? sg.itemid : null, name: sg.name, direction: sg.direction,
      in_dataset: sg.in_dataset != null ? sg.in_dataset : sg.itemid != null,
      rationale: sg.rationale || "", evidence: sg.evidence || "",
      citation: sg.citation || { title: "", url: "" },
    })));
    setMinSignals(s.min_signals || 1);
    setMessages([]); kickedOff.current = true; // don't auto-kickoff for a loaded one
    setRun(null); setSaveMsg(null);
    setStep(3); // resume straight at the patterns review
  }

  async function deleteSyndrome(key, e) {
    e.stopPropagation();
    if (!window.confirm("Delete this saved syndrome?")) return;
    await fetch(`/api/builder/syndromes/${key}`, { method: "DELETE" }).catch(() => {});
    if (key === currentKey) setCurrentKey(null);
    loadSaved();
  }

  function startOver() {
    setName(""); setDescription(""); setCurrentKey(null);
    setRules([]); setMinSignals(1); setRun(null); setSaveMsg(null);
    setMessages([]); kickedOff.current = false; setStep(1);
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

  const canGo = (target) => target === 1 || (target >= 2 && name.trim());
  const go = (target) => { if (canGo(target)) setStep(target); };

  const SUGGESTIONS = name.trim() ? [
    `What lab patterns point to ${name.trim()}?`,
    `Which lab values are most specific to ${name.trim()}?`,
    `Summarise the evidence and propose pattern rules for ${name.trim()}.`,
  ] : [];

  return (
    <div className="bld">
      <div className="bldintro">
        <h2><Icon name="construction" /> Pattern Builder</h2>
        <p>Build an evidence-based syndrome in three steps: name it, co-research the
          pattern rules with the AI (it searches real literature and summarises it here),
          then review and try the rule set on real patient data. Educational prototype — not medical advice.</p>
      </div>

      {/* ── Stepper ── */}
      <div className="bldsteps">
        {STEPS.map((s, i) => (
          <React.Fragment key={s.n}>
            <button
              className={`bldstep ${step === s.n ? "active" : ""} ${step > s.n ? "done" : ""}`}
              disabled={!canGo(s.n)} onClick={() => go(s.n)}>
              <span className="bldstep-num">{step > s.n ? <Icon name="check" /> : s.n}</span>
              <span className="bldstep-lbl"><Icon name={s.icon} className="bldstep-ic" />{s.label}</span>
            </button>
            {i < STEPS.length - 1 && <span className={`bldstep-bar ${step > s.n ? "done" : ""}`} />}
          </React.Fragment>
        ))}
      </div>

      {/* ── STEP 1: choose the syndrome ── */}
      {step === 1 && (
        <div className="bldstage">
          <div className="bldcard">
            <h3>1 · Which syndrome do you want to build?</h3>
            <p className="bldlede">Give it a name (it can be a known syndrome or a candidate
              you're investigating). You can refine everything later.</p>
            <div className="bldfield">
              <label>Syndrome name</label>
              <input value={name} onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Hepatorenal Syndrome"
                onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) go(2); }} autoFocus />
            </div>
            <div className="bldchips">
              {EXAMPLES.map((ex) => (
                <button key={ex} className={name === ex ? "on" : ""} onClick={() => setName(ex)}>{ex}</button>
              ))}
            </div>
            <div className="bldfield">
              <label>Working description <span className="bldopt">(optional)</span></label>
              <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="What is this syndrome, and what are you trying to capture?" />
            </div>
            <div className="bldnav">
              <span />
              <button className="bldprimary" disabled={!name.trim()} onClick={() => go(2)}>
                Start co-research <Icon name="arrow_forward" />
              </button>
            </div>
          </div>

          {saved.length > 0 && (
            <div className="bldcard">
              <h3>…or resume a saved syndrome</h3>
              <ul className="bldsaved">
                {saved.map((s) => (
                  <li key={s.key} onClick={() => loadSyndrome(s)}>
                    <div>
                      <div className="bldsaved-name">{s.name}</div>
                      <div className="bldsaved-meta">{s.signals.length} pattern{s.signals.length !== 1 ? "s" : ""} · fires at ≥ {s.min_signals}</div>
                    </div>
                    <button className="bldrm" onClick={(e) => deleteSyndrome(s.key, e)} aria-label="Delete"><Icon name="delete" /></button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ── STEP 2: co-research with the AI ── */}
      {step === 2 && (
        <div className="bldstage">
          <div className="bldcard bldchat">
            <div className="bldchat-head">
              <span className="bldavatar"><Icon name="smart_toy" /></span>
              <div>
                <div className="bldname">Co-research: <span className="bldhl">{name}</span></div>
                <div className="bldsub"><Icon name="travel_explore" /> Searches the literature and summarises it here</div>
              </div>
              <span className="bldcount" title="Patterns chosen so far">
                <Icon name="checklist" />{rules.length}
              </span>
            </div>

            <div className="bldchat-body bldchat-tall" ref={bodyRef}>
              {messages.length === 0 && !chatLoading && (
                <div className="bldwelcome">
                  <p>Let's research <strong>{name}</strong> together and agree on the lab patterns
                    that point to it. Try:</p>
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
                        <div className="bldprops-h">Proposed patterns</div>
                        {m.proposals.map((p, j) => {
                          const added = hasRule(p);
                          return (
                            <div key={j} className="bldprop">
                              <div className="bldprop-main">
                                <span className="bldpillwrap">
                                  <span className={`bldpill ${p.direction}`}>{p.name} {dirLabel(p.direction)}</span>
                                  {!p.in_dataset && <span className="bldtag-ro" title="This lab isn't in the dataset — saved for research, can't be tested on patient data">research-only</span>}
                                </span>
                                <button className="bldadd" disabled={added} onClick={() => addRule(p)}>
                                  <Icon name={added ? "check" : "add"} />{added ? "Added" : "Add"}
                                </button>
                              </div>
                              {p.rationale && <div className="bldprop-rat">{p.rationale}</div>}
                              {p.evidence && (
                                <div className="bldevidence"><Icon name="menu_book" /><span>{p.evidence}</span></div>
                              )}
                              <Citation citation={p.citation} />
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {(m.citations || []).length > 0 && (
                      <div className="bldsources">
                        <span>Sources:</span>
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
              <textarea rows={1} value={input} placeholder="Discuss, refine, or ask for more evidence…"
                onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} disabled={chatLoading} />
              <button onClick={() => send()} disabled={chatLoading || !input.trim()} aria-label="Send">
                <Icon name="send" />
              </button>
            </div>
          </div>

          <div className="bldnav">
            <button className="bldghost" onClick={() => go(1)}><Icon name="arrow_back" />Back</button>
            <button className="bldprimary" onClick={() => go(3)} disabled={!rules.length}>
              Review patterns ({rules.length}) <Icon name="arrow_forward" />
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 3: chosen patterns ── */}
      {step === 3 && (
        <div className="bldstage">
          <div className="bldcard">
            <div className="bldcard-head">
              <h3>3 · Patterns for <span className="bldhl">{name}</span></h3>
              <button className="bldghost" onClick={() => go(2)} title="Back to co-research">
                <Icon name="travel_explore" />Research more
              </button>
            </div>

            {rules.length === 0 ? (
              <div className="bldempty">No patterns yet. Go back to co-research, or add one manually below.</div>
            ) : (
              <ul className="bldrules">
                {rules.map((r) => (
                  <li key={ruleKey(r)} className="bldrule">
                    <span className="bldpillwrap">
                      <span className={`bldpill ${r.direction}`}>{r.name} {dirLabel(r.direction)}</span>
                      {!r.in_dataset && <span className="bldtag-ro" title="Not in the dataset — saved for research, not tested on patient data">research-only</span>}
                    </span>
                    <div className="bldrule-body">
                      {r.rationale && <div className="bldrule-rat">{r.rationale}</div>}
                      {r.evidence && <div className="bldevidence"><Icon name="menu_book" /><span>{r.evidence}</span></div>}
                      <Citation citation={r.citation} />
                    </div>
                    <button className="bldrm" onClick={() => removeRule(r)} aria-label="Remove pattern">
                      <Icon name="close" />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="bldmanual">
              <div className="bldpicker">
                <input value={pickQuery} placeholder={`Search ${catalog.length || ""} labs by name or category…`}
                  onChange={(e) => { setPickQuery(e.target.value); setPicked(null); setPickOpen(true); }}
                  onFocus={() => setPickOpen(true)}
                  onBlur={() => setTimeout(() => setPickOpen(false), 150)}
                  onKeyDown={(e) => { if (e.key === "Enter") addManual(); }} />
                {pickOpen && pickMatches.length > 0 && (
                  <ul className="bldpicklist">
                    {pickMatches.map((l) => (
                      <li key={l.itemid} onMouseDown={() => choosePick(l)}>
                        <span className="bldpicklabel">{l.label}</span>
                        <span className="bldpickmeta">
                          {l.category && <span className="bldcatchip">{l.category}</span>}
                          {l.testable
                            ? <span className="bldtag-ok">testable</span>
                            : <span className="bldtag-ro">research-only</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <select value={pickDir} onChange={(e) => setPickDir(e.target.value)}>
                <option value="high">↑ High</option>
                <option value="low">↓ Low</option>
              </select>
              <button className="bldghost" onClick={addManual} disabled={!pickQuery.trim()}><Icon name="add" />Add</button>
            </div>
            <div className="bldhint">Pick any of the {catalog.length || ""} labs in the dataset. <b>Testable</b> labs run on patient data; others are saved as research-only.</div>

            {rules.length > 0 && (
              <div className="bldthresh">
                <label>Fires when at least</label>
                <select value={minSignals} onChange={(e) => setMinSignals(Number(e.target.value))}>
                  {Array.from({ length: rules.length }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
                <label>of {rules.length} pattern{rules.length > 1 ? "s" : ""} match.</label>
              </div>
            )}

            <div className="bldactions">
              <button className="bldprimary" onClick={saveSyndrome} disabled={!name.trim() || !rules.length}>
                <Icon name="save" />{currentKey ? "Update" : "Save"} syndrome
              </button>
              <button className="bldsecondary" onClick={runOnData} disabled={!rules.length || runLoading}>
                <Icon name="science" />{runLoading ? "Running…" : "Run on patient data"}
              </button>
              <button className="bldghost" onClick={startOver}><Icon name="restart_alt" />Start over</button>
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
                    <div className="bldstat"><b>≥ {run.min_signals}</b><span>of {run.n_runnable ?? run.n_rules} testable</span></div>
                  </div>
                  {run.note && <div className="bldnote warn">{run.note}</div>}
                  {run.skipped?.length > 0 && (
                    <div className="bldskipped">
                      <Icon name="info" />
                      <span>Not tested (lab not in dataset): {run.skipped.map((s) => `${s.name} ${s.direction === "high" ? "↑" : "↓"}`).join(", ")}</span>
                    </div>
                  )}
                  {run.examples?.length > 0 ? (
                    <table className="bldtable">
                      <thead><tr><th>Patient</th><th>Admission</th><th>Matched labs</th></tr></thead>
                      <tbody>
                        {run.examples.map((m) => (
                          <tr key={`${m.subject_id}-${m.hadm_id}`}>
                            <td>{m.subject_id}</td>
                            <td>{m.hadm_id}</td>
                            <td>{m.matched.map((h) => (
                              <span key={h.itemid} className={`bldtag ${h.direction}`}>{h.name} {h.value}</span>
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
        </div>
      )}
    </div>
  );
}
