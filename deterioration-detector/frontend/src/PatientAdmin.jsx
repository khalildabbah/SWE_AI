import React, { useEffect, useRef, useState } from "react";

/*
 * Adding and deleting admissions.
 *
 * Both actions write to the analytical database, so both are deliberate: the
 * form validates against the same bounds the ingestion pipeline uses (fetched
 * from /api/labs) before it will submit, and the delete is gated behind a
 * dialog that says exactly what is about to disappear.
 */

const Icon = ({ name, className = "" }) => (
  <span className={`material-symbols-outlined ${className}`}>{name}</span>
);

/* "2026-08-16T14:00" — what <input type="datetime-local"> expects. */
const toLocalInput = (date) => {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`
    + `T${p(date.getHours())}:${p(date.getMinutes())}`;
};

const hoursFromNow = (h) => {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + h);
  return toLocalInput(d);
};

/* ── Shared modal shell ─────────────────────────────────────────────────── */

function Modal({ title, sub, icon, tone = "", onClose, children, footer }) {
  const ref = useRef(null);

  // Escape closes; focus moves into the dialog so keyboard users start inside it.
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector("input, select, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modalwrap" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${tone}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="modalhead">
          <div className="modaltitle">
            <Icon name={icon} />
            <div>
              <h3>{title}</h3>
              {sub && <div className="modalsub">{sub}</div>}
            </div>
          </div>
          <button className="modalclose" type="button" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        <div className="modalbody">{children}</div>
        <div className="modalfoot">{footer}</div>
      </div>
    </div>
  );
}

/* ── Add a new patient ──────────────────────────────────────────────────── */

const blankRow = (i) => ({ itemid: "", value: "", charttime: hoursFromNow(i * 6 - 12) });

function AddPatientDialog({ onClose, onCreated }) {
  const [labs, setLabs] = useState([]);
  const [subjectId, setSubjectId] = useState("");
  const [hadmId, setHadmId] = useState("");
  const [rows, setRows] = useState([blankRow(0), blankRow(1), blankRow(2)]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/labs").then((r) => r.json()).then((d) => setLabs(d.items || []))
      .catch(() => setError("Couldn't load the lab list — is the API running?"));
  }, []);

  const byId = Object.fromEntries(labs.map((l) => [String(l.itemid), l]));
  const setRow = (i, patch) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const addRow = () => setRows((rs) => [...rs, blankRow(rs.length)]);
  const removeRow = (i) => setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : rs));

  /* Mirrors the server's rules so the common mistakes are caught before a
     round-trip; the server stays the authority either way. */
  const problems = [];
  if (!/^\d+$/.test(subjectId)) problems.push("A numeric patient ID is required.");
  if (!/^\d+$/.test(hadmId)) problems.push("A numeric admission ID is required.");
  const filled = rows.filter((r) => r.itemid !== "" || r.value !== "");
  if (!filled.length) problems.push("Add at least one lab measurement.");
  filled.forEach((r, i) => {
    const lab = byId[r.itemid];
    const n = i + 1;
    if (!lab) { problems.push(`Measurement ${n}: choose a lab test.`); return; }
    if (r.value === "" || Number.isNaN(+r.value)) {
      problems.push(`Measurement ${n} (${lab.name}): enter a numeric value.`);
    } else if (+r.value < lab.plausible_min || +r.value > lab.plausible_max) {
      problems.push(`Measurement ${n} (${lab.name}): must be between `
        + `${lab.plausible_min} and ${lab.plausible_max} ${lab.unit}.`);
    }
    if (!r.charttime) problems.push(`Measurement ${n} (${lab.name}): pick a date and time.`);
  });
  const seen = new Set();
  filled.forEach((r, i) => {
    const key = `${r.itemid}@${r.charttime}`;
    if (r.itemid && r.charttime && seen.has(key)) {
      problems.push(`Measurement ${i + 1}: duplicate reading for the same lab and time.`);
    }
    seen.add(key);
  });

  const submit = async () => {
    if (problems.length || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/admissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject_id: +subjectId,
          hadm_id: +hadmId,
          measurements: filled.map((r) => ({
            itemid: +r.itemid, value: +r.value, charttime: r.charttime,
          })),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "The server rejected this admission.");
      onCreated(body);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Add New Patient" icon="person_add"
      sub="Enter an admission and its lab readings. It is scored by the same engine as every other patient."
      onClose={onClose}
      footer={
        <>
          <span className="modalhint">
            {filled.length} measurement{filled.length === 1 ? "" : "s"}
            {problems.length > 0 && <> · <span className="bad">{problems.length} to fix</span></>}
          </span>
          <button className="btnghost" type="button" onClick={onClose}>Cancel</button>
          <button className="btnprimary" type="button" onClick={submit}
            disabled={busy || problems.length > 0 || !labs.length}>
            <Icon name={busy ? "progress_activity" : "check"} className={busy ? "spin" : ""} />
            {busy ? "Adding…" : "Add Patient"}
          </button>
        </>
      }
    >
      {error && <div className="formerr"><Icon name="error" />{error}</div>}

      <div className="formgrid two">
        <label className="field">
          <span>Patient ID</span>
          <input type="text" inputMode="numeric" value={subjectId} placeholder="e.g. 990001"
            onChange={(e) => setSubjectId(e.target.value.replace(/\D/g, ""))} />
        </label>
        <label className="field">
          <span>Admission ID</span>
          <input type="text" inputMode="numeric" value={hadmId} placeholder="e.g. 890001"
            onChange={(e) => setHadmId(e.target.value.replace(/\D/g, ""))} />
        </label>
      </div>

      <div className="fieldhead">
        <span>Lab measurements</span>
        <span className="muted">
          Three or more readings of the same lab let the trend detector see a direction.
        </span>
      </div>

      <div className="measrows">
        {rows.map((r, i) => {
          const lab = byId[r.itemid];
          return (
            <div className="measrow" key={i}>
              <select value={r.itemid} onChange={(e) => setRow(i, { itemid: e.target.value })}>
                <option value="">Select lab…</option>
                {labs.map((l) => <option key={l.itemid} value={l.itemid}>{l.name}</option>)}
              </select>
              <div className="measval">
                <input type="number" step="any" value={r.value} placeholder="Value"
                  onChange={(e) => setRow(i, { value: e.target.value })} />
                {lab && <span className="measunit">{lab.unit}</span>}
              </div>
              <input type="datetime-local" value={r.charttime}
                onChange={(e) => setRow(i, { charttime: e.target.value })} />
              <button className="measrm" type="button" onClick={() => removeRow(i)}
                disabled={rows.length === 1} aria-label="Remove measurement">
                <Icon name="close" />
              </button>
              {lab && (
                <div className="meashint">
                  Normal {lab.normal_low}–{lab.normal_high} {lab.unit}
                  <span className="dim"> · accepted {lab.plausible_min}–{lab.plausible_max}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <button className="btnghost small" type="button" onClick={addRow}>
        <Icon name="add" />Add measurement
      </button>

      {problems.length > 0 && (
        <ul className="formproblems">
          {problems.slice(0, 6).map((p, i) => <li key={i}>{p}</li>)}
          {problems.length > 6 && <li>…and {problems.length - 6} more.</li>}
        </ul>
      )}
    </Modal>
  );
}

/* ── Delete the selected patient ────────────────────────────────────────── */

function DeletePatientDialog({ d, meta, onClose, onDeleted }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const nLabs = d.labs?.length ?? 0;
  const nMeasurements = meta?.n_measurements
    ?? (d.labs || []).reduce((s, l) => s + l.points.length, 0);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/admissions/${d.subject_id}/${d.hadm_id}`, { method: "DELETE" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "The server refused to delete this admission.");
      onDeleted(body);
    } catch (e) {
      setError(String(e.message || e));
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Delete this patient?" icon="delete" tone="danger"
      sub="This permanently removes the admission from the analytical database."
      onClose={onClose}
      footer={
        <>
          <span className="modalhint" />
          <button className="btnghost" type="button" onClick={onClose}>Cancel</button>
          <button className="btndanger" type="button" onClick={confirm} disabled={busy}>
            <Icon name={busy ? "progress_activity" : "delete_forever"} className={busy ? "spin" : ""} />
            {busy ? "Deleting…" : "Delete permanently"}
          </button>
        </>
      }
    >
      {error && <div className="formerr"><Icon name="error" />{error}</div>}

      <div className="delsummary">
        <div className="delwho">
          <div className="delname">Patient {d.subject_id}</div>
          <div className="deladm">Admission ID {d.hadm_id}</div>
        </div>
        <span className={`chip ${d.risk.category}`}>
          {d.risk.category} · <span className="pts">{d.risk.score}</span>
        </span>
      </div>

      <div className="dellist">
        <div><Icon name="science" /><b>{nMeasurements.toLocaleString()}</b> lab measurements across <b>{nLabs}</b> tests</div>
        <div><Icon name="monitoring" />Its risk score, trajectory and alerts</div>
        <div><Icon name="schedule" />Its early-warning lead-time record</div>
        <div><Icon name="format_list_numbered" />Its place in the triage board and any pattern rankings</div>
      </div>

      <p className="delnote">
        <Icon name="info" />
        Admissions loaded from MIMIC can be restored by re-running the data
        pipeline; a patient added here by hand cannot be recovered.
      </p>
    </Modal>
  );
}

/* ── The two buttons, plus whichever dialog is open ─────────────────────── */

export default function PatientActions({ d, meta, onCreated, onDeleted }) {
  const [open, setOpen] = useState(null); // "add" | "delete" | null

  return (
    <>
      <button className="btnghost" type="button" onClick={() => setOpen("add")}>
        <Icon name="person_add" />Add New Patient
      </button>
      <button className="btndangerghost" type="button" onClick={() => setOpen("delete")}
        disabled={!d} title={d ? `Delete patient ${d.subject_id}` : "No patient selected"}>
        <Icon name="delete" />Delete Patient
      </button>

      {open === "add" && (
        <AddPatientDialog
          onClose={() => setOpen(null)}
          onCreated={(res) => { setOpen(null); onCreated(res); }} />
      )}
      {open === "delete" && d && (
        <DeletePatientDialog
          d={d} meta={meta}
          onClose={() => setOpen(null)}
          onDeleted={(res) => { setOpen(null); onDeleted(res); }} />
      )}
    </>
  );
}
