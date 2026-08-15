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
 *
 * A saved pattern isn't the end of the road: it is evaluated on every patient
 * alongside the built-in syndromes, and a run result links straight through to
 * the patient it found (`onOpenPatient`).
 */

const Icon = ({ name, className = "" }) => (
  <span className={`material-symbols-outlined ${className}`}>{name}</span>
);

const STEPS = [
  { n: 1, label: "Choose Disease", icon: "label" },
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

/* What a rule actually fires at, in words: "> 1.2 mg/dL".
 * "High" on its own is not a number, and a user agreeing to a rule deserves to
 * see the value it will be tested at — especially when their own evidence
 * quotes a different one. */
function ruleBound(rule, lab) {
  const custom = rule.threshold != null && rule.threshold !== "";
  const fallback = rule.direction === "high" ? lab?.normal_high : lab?.normal_low;
  const value = custom ? Number(rule.threshold) : fallback;
  if (value == null || Number.isNaN(value)) return null;
  const unit = lab?.units ? ` ${lab.units}` : "";
  return {
    text: `${rule.direction === "high" ? ">" : "<"} ${value}${unit}`,
    custom,
  };
}

function Bound({ rule, lab }) {
  const b = ruleBound(rule, lab);
  if (!b) return null;
  return (
    <span className={`bldbound ${b.custom ? "custom" : ""}`}
      title={b.custom
        ? "This rule's own threshold, from the evidence — not the lab's reference range."
        : "The edge of this lab's normal reference range. Set a threshold on the rule to fire at the value your source states instead."}>
      {b.text}
    </span>
  );
}

function Citation({ citation }) {
  if (citation?.url)
    return <a className="bldcite" href={citation.url} target="_blank" rel="noreferrer">
      <Icon name="link" />{citation.title || citation.url}</a>;
  if (citation?.title)
    return <div className="bldcite nolink"><Icon name="menu_book" />{citation.title}</div>;
  return null;
}

export default function Builder({ onOpenPatient }) {
  const [step, setStep] = useState(1);

  const [catalog, setCatalog] = useState([]); // {itemid,label,category,units,testable,n_rows}
  const [saved, setSaved] = useState([]);
  const [storage, setStorage] = useState(null); // "motherduck" | "file"

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [currentKey, setCurrentKey] = useState(null);

  const [rules, setRules] = useState([]); // {itemid,name,direction,rationale,evidence,citation}
  const [minSignals, setMinSignals] = useState(1);
  const [editing, setEditing] = useState(null); // ruleKey of the rule being edited

  // co-work chat
  const [messages, setMessages] = useState([]); // {role,text,proposals?,citations?,failed?}
  const [input, setInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const bodyRef = useRef(null);
  const abortRef = useRef(null);
  // The syndrome name the current conversation belongs to. Renaming at step 1
  // makes the old conversation irrelevant, so it starts fresh instead.
  const [researchedFor, setResearchedFor] = useState(null);

  // manual add (lab pick-list) + actions
  const [pickQuery, setPickQuery] = useState("");
  const [picked, setPicked] = useState(null);   // chosen catalog lab
  const [pickOpen, setPickOpen] = useState(false);
  const [pickDir, setPickDir] = useState("high");
  const [saveMsg, setSaveMsg] = useState(null);
  const [run, setRun] = useState(null);
  const [runLoading, setRunLoading] = useState(false);
  const importRef = useRef(null);

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

  // Entering co-research kicks off the conversation so the step is immediately
  // productive. Re-kicks if the syndrome was renamed, since the previous
  // conversation was about a different question.
  useEffect(() => {
    if (step !== 2) return;
    const subject = name.trim();
    if (!subject || researchedFor === subject) return;
    setResearchedFor(subject);
    setMessages([]);
    send(`Let's build lab-based pattern rules for "${subject}". Search the `
      + `literature and propose pattern rules (a lab + a direction) — summarise the `
      + `key evidence here so I can decide without leaving the page.`, []);
  }, [step, name]); // eslint-disable-line react-hooks/exhaustive-deps

  // Abandon an in-flight research turn if the user navigates away mid-search.
  useEffect(() => () => abortRef.current?.abort(), []);

  function loadSaved() {
    fetch("/api/builder/syndromes").then((r) => r.json())
      .then((d) => { setSaved(d.items || []); setStorage(d.storage || null); })
      .catch(() => {});
  }

  // testable (tracked) labs, keyed by lowercased label, for resolving names
  const testableByName = useMemo(() => Object.fromEntries(
    catalog.filter((l) => l.testable).map((l) => [l.label.toLowerCase(), l])), [catalog]);
  // …and by itemid, so a rule can show the value it fires at
  const labById = useMemo(() => Object.fromEntries(
    catalog.filter((l) => l.testable).map((l) => [l.itemid, l])), [catalog]);
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
      threshold: rule.threshold != null ? rule.threshold : null,
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

  // Edit one rule in place. Keyed by the rule's identity BEFORE the edit,
  // because changing the direction changes that identity.
  function updateRule(key, patch) {
    setRules((rs) => rs.map((r) => (ruleKey(r) === key ? { ...r, ...patch } : r)));
    setRun(null);
  }

  function updateCitation(key, patch) {
    setRules((rs) => rs.map((r) => (ruleKey(r) === key
      ? { ...r, citation: { ...(r.citation || {}), ...patch } } : r)));
  }

  // Flipping the direction changes the rule's identity, so the open editor has
  // to follow it — and the flip is refused if it would collide with a rule that
  // already exists.
  function changeDirection(rule, direction) {
    if (direction === rule.direction) return;
    const next = { ...rule, direction };
    if (hasRule(next)) return;
    const from = ruleKey(rule);
    updateRule(from, { direction });
    setEditing((cur) => (cur === from ? ruleKey(next) : cur));
  }

  // A rule nobody sourced — worth flagging, since the whole point is evidence.
  const isUncited = (r) => !(r.citation?.url || r.citation?.title);

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

  /* One co-research turn.
   * `historyOverride` lets the kickoff pass an explicit (empty) history, since
   * the `messages` reset it depends on hasn't been applied yet at that point.
   * A web-searched turn can take 30s+, so it is always abortable. */
  async function send(text, historyOverride) {
    const msg = (text ?? input).trim();
    if (!msg || chatLoading) return;
    setInput("");
    const history = historyOverride
      ?? messages.filter((m) => !m.failed).map((m) => ({ role: m.role, text: m.text }));
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setChatLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const r = await fetch("/api/builder/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, message: msg, history }),
        signal: controller.signal,
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setMessages((m) => [...m, {
          role: "model", failed: true, retry: msg, retryHistory: history,
          text: data.detail || "The builder AI hit an error. Please try again.",
        }]);
      } else {
        setMessages((m) => [...m, {
          role: "model", text: data.reply,
          proposals: data.proposals || [], citations: data.citations || [],
        }]);
      }
    } catch (e) {
      if (e.name === "AbortError") {
        setMessages((m) => [...m, {
          role: "model", failed: true, retry: msg, retryHistory: history,
          text: "Search cancelled.",
        }]);
      } else {
        setMessages((m) => [...m, {
          role: "model", failed: true, retry: msg, retryHistory: history,
          text: "Couldn't reach the builder AI — is the API running?",
        }]);
      }
    } finally {
      abortRef.current = null;
      setChatLoading(false);
    }
  }

  function cancelSend() {
    abortRef.current?.abort();
  }

  // Retry drops just the failed exchange — that error and the question that
  // produced it — so the conversation isn't littered with errors while
  // everything said before it is preserved. Then it re-sends the original
  // question against the history it originally had.
  function retrySend(msg, index) {
    setMessages((m) => {
      const from = index > 0 && m[index - 1]?.role === "user" ? index - 1 : index;
      return [...m.slice(0, from), ...m.slice(index + 1)];
    });
    send(msg.retry, msg.retryHistory);
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
      threshold: sg.threshold != null ? sg.threshold : null,
      rationale: sg.rationale || "", evidence: sg.evidence || "",
      citation: sg.citation || { title: "", url: "" },
    })));
    setMinSignals(s.min_signals || 1);
    // A resumed pattern already has its rules; don't auto-start a conversation.
    setMessages([]); setResearchedFor(s.name);
    setRun(null); setSaveMsg(null); setEditing(null);
    setStep(3); // resume straight at the patterns review
  }

  async function deleteSyndrome(key, e) {
    e.stopPropagation();
    if (!window.confirm("Delete this saved pattern?")) return;
    await fetch(`/api/builder/syndromes/${key}`, { method: "DELETE" }).catch(() => {});
    if (key === currentKey) setCurrentKey(null);
    loadSaved();
  }

  function startOver() {
    setName(""); setDescription(""); setCurrentKey(null);
    setRules([]); setMinSignals(1); setRun(null); setSaveMsg(null);
    setMessages([]); setResearchedFor(null); setEditing(null); setStep(1);
  }

  /* Export / import — a portable copy of everything saved, so research survives
   * a server rebuild regardless of where the backend stores it. */
  async function exportAll() {
    try {
      const r = await fetch("/api/builder/export");
      const data = await r.json();
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "pattern-builder-export.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setSaveMsg({ ok: false, text: "Couldn't export — is the API running?" });
    }
  }

  async function importFile(file) {
    if (!file) return;
    setSaveMsg(null);
    try {
      const payload = JSON.parse(await file.text());
      const items = Array.isArray(payload) ? payload : (payload.items || []);
      if (!items.length) { setSaveMsg({ ok: false, text: "That file has no patterns in it." }); return; }
      const r = await fetch("/api/builder/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setSaveMsg({ ok: false, text: data.detail || "Import failed." }); return; }
      const skipped = data.failed?.length ? ` ${data.failed.length} skipped.` : "";
      setSaveMsg({ ok: true, text: `Imported ${data.n_imported} pattern(s).${skipped}` });
      loadSaved();
    } catch {
      setSaveMsg({ ok: false, text: "That doesn't look like a Pattern Builder export." });
    }
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
        <p>Build an evidence-based pattern in three steps: name the disease or syndrome, co-research the
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
            <h3>1 · Which disease or possible syndrome do you want to investigate?</h3>
            <p className="bldlede">Give it a name — a disease, a syndrome, or any candidate
              condition you're investigating. You can refine everything later.</p>
            <div className="bldfield">
              <label>Disease / syndrome name</label>
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
                placeholder="What is this disease or syndrome, and what are you trying to capture?" />
            </div>
            <div className="bldnav">
              <span />
              <button className="bldprimary" disabled={!name.trim()} onClick={() => go(2)}>
                Start co-research <Icon name="arrow_forward" />
              </button>
            </div>
          </div>

          <div className="bldcard">
            <div className="bldcard-head">
              <h3>{saved.length > 0 ? "…or resume a saved pattern" : "Saved patterns"}</h3>
              <div className="bldio">
                <button className="bldghost" onClick={exportAll} disabled={!saved.length}
                  title="Download every saved pattern as JSON">
                  <Icon name="download" />Export
                </button>
                <button className="bldghost" onClick={() => importRef.current?.click()}
                  title="Restore patterns from an exported JSON file">
                  <Icon name="upload" />Import
                </button>
                <input ref={importRef} type="file" accept="application/json,.json" hidden
                  onChange={(e) => { importFile(e.target.files?.[0]); e.target.value = ""; }} />
              </div>
            </div>
            {saved.length === 0 ? (
              <div className="bldempty">Nothing saved yet — build your first pattern above, or import an export.</div>
            ) : (
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
            )}
            {storage && (
              <div className="bldhint">
                {storage === "motherduck"
                  ? "Stored in the cloud database — these survive a redeploy."
                  : "Stored on this server's disk. If it's redeployed they're gone, so export a copy you care about."}
              </div>
            )}
            {saveMsg && step === 1 && (
              <div className={`bldnote ${saveMsg.ok ? "ok" : "err"}`}>{saveMsg.text}</div>
            )}
          </div>
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
                  <div className={`bldbubble ${m.failed ? "failed" : ""}`}>
                    <div className="bldtext">{renderText(m.text)}</div>

                    {m.failed && (
                      <button className="bldretry" onClick={() => retrySend(m, i)} disabled={chatLoading}>
                        <Icon name="refresh" />Try again
                      </button>
                    )}

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
                                  <Bound rule={p} lab={labById[p.itemid]} />
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
                  <div className="bldbubble">
                    <div className="bldtyping"><span /><span /><span /></div>
                    <div className="bldsearching">
                      Searching the literature — this can take up to a minute.
                      <button className="bldcancel" onClick={cancelSend}>Cancel</button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="bldchat-input">
              <textarea rows={1} value={input} placeholder="Discuss, refine, or ask for more evidence…"
                onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} disabled={chatLoading} />
              {chatLoading ? (
                <button className="stop" onClick={cancelSend} aria-label="Stop">
                  <Icon name="stop_circle" />
                </button>
              ) : (
                <button onClick={() => send()} disabled={!input.trim()} aria-label="Send">
                  <Icon name="send" />
                </button>
              )}
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
                {rules.map((r) => {
                  const key = ruleKey(r);
                  const open = editing === key;
                  return (
                    <li key={key} className={`bldrule ${open ? "editing" : ""}`}>
                      <span className="bldpillwrap">
                        <span className={`bldpill ${r.direction}`}>{r.name} {dirLabel(r.direction)}</span>
                        <Bound rule={r} lab={labById[r.itemid]} />
                        {!r.in_dataset && <span className="bldtag-ro" title="Not in the dataset — saved for research, not tested on patient data">research-only</span>}
                        {isUncited(r) && <span className="bldtag-un" title="No source attached — add one so this rule is as evidence-backed as the rest">uncited</span>}
                      </span>

                      {open ? (
                        <div className="bldrule-edit">
                          <label>Direction
                            <select value={r.direction}
                              onChange={(e) => changeDirection(r, e.target.value)}>
                              <option value="high">↑ High</option>
                              <option value="low">↓ Low</option>
                            </select>
                          </label>
                          {r.in_dataset && (
                            <label>Fires at
                              <div className="bldthresholdrow">
                                <span className="bldcmp">{r.direction === "high" ? ">" : "<"}</span>
                                <input type="number" step="any" value={r.threshold ?? ""}
                                  placeholder={String(r.direction === "high"
                                    ? labById[r.itemid]?.normal_high ?? ""
                                    : labById[r.itemid]?.normal_low ?? "")}
                                  onChange={(e) => updateRule(key, {
                                    threshold: e.target.value === "" ? null : Number(e.target.value),
                                  })} />
                                <span className="bldunit">{labById[r.itemid]?.units}</span>
                                {r.threshold != null && (
                                  <button className="bldcancel" type="button"
                                    onClick={() => updateRule(key, { threshold: null })}>
                                    use normal range
                                  </button>
                                )}
                              </div>
                              <span className="bldfieldhint">
                                {r.threshold != null
                                  ? "Your source's cut-off — this is the value the rule is tested at."
                                  : `Empty means the edge of the normal range (${labById[r.itemid]?.normal_low}–${labById[r.itemid]?.normal_high} ${labById[r.itemid]?.units || ""}). If your evidence states a cut-off, put it here.`}
                              </span>
                            </label>
                          )}
                          <label>Rationale
                            <textarea rows={2} value={r.rationale} placeholder="One plain sentence: why this lab, this direction?"
                              onChange={(e) => updateRule(key, { rationale: e.target.value })} />
                          </label>
                          <label>Evidence
                            <textarea rows={3} value={r.evidence} placeholder="What the source actually says, so a reader can decide without opening it."
                              onChange={(e) => updateRule(key, { evidence: e.target.value })} />
                          </label>
                          <div className="bldrule-cite">
                            <label>Source title
                              <input value={r.citation?.title || ""} placeholder="e.g. KDIGO AKI Guideline"
                                onChange={(e) => updateCitation(key, { title: e.target.value })} />
                            </label>
                            <label>Source URL
                              <input value={r.citation?.url || ""} placeholder="https://…"
                                onChange={(e) => updateCitation(key, { url: e.target.value })} />
                            </label>
                          </div>
                          <button className="bldghost" onClick={() => setEditing(null)}>
                            <Icon name="check" />Done
                          </button>
                        </div>
                      ) : (
                        <div className="bldrule-body">
                          {r.rationale && <div className="bldrule-rat">{r.rationale}</div>}
                          {r.evidence && <div className="bldevidence"><Icon name="menu_book" /><span>{r.evidence}</span></div>}
                          <Citation citation={r.citation} />
                        </div>
                      )}

                      <div className="bldrule-acts">
                        <button className="bldrm" onClick={() => setEditing(open ? null : key)}
                          aria-label={open ? "Close editor" : "Edit pattern"} title="Edit this rule">
                          <Icon name={open ? "expand_less" : "edit"} />
                        </button>
                        <button className="bldrm" onClick={() => removeRule(r)} aria-label="Remove pattern">
                          <Icon name="close" />
                        </button>
                      </div>
                    </li>
                  );
                })}
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
                <Icon name="save" />{currentKey ? "Update" : "Save"} pattern
              </button>
              <button className="bldsecondary" onClick={runOnData} disabled={!rules.length || runLoading}>
                <Icon name="science" />{runLoading ? "Running…" : "Run on patient data"}
              </button>
              <button className="bldghost" onClick={startOver}><Icon name="restart_alt" />Start over</button>
            </div>
            {saveMsg && <div className={`bldnote ${saveMsg.ok ? "ok" : "err"}`}>{saveMsg.text}</div>}
            <div className="bldhint">
              Saved patterns are checked against every patient — a match shows up
              as a card on their Patient Monitoring page.
              {storage === "file" && " They're stored on this server only, so keep a copy with Export."}
            </div>
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
                    <>
                      <table className="bldtable">
                        <thead><tr><th>Patient</th><th>Admission</th><th>Matched labs</th><th /></tr></thead>
                        <tbody>
                          {run.examples.map((m) => (
                            <tr key={`${m.subject_id}-${m.hadm_id}`}
                              className={onOpenPatient ? "clickable" : ""}
                              onClick={() => onOpenPatient?.(m.subject_id, m.hadm_id)}>
                              <td>{m.subject_id}</td>
                              <td>{m.hadm_id}</td>
                              <td>{m.matched.map((h) => (
                                <span key={h.itemid} className={`bldtag ${h.direction}`}>{h.name} {h.value}</span>
                              ))}</td>
                              <td className="bldgo">{onOpenPatient && <Icon name="arrow_forward" />}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {onOpenPatient && (
                        <div className="bldhint">Click a row to open that patient in Patient Monitoring.</div>
                      )}
                    </>
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
