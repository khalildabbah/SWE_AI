/*
 * Patient report → PDF.
 *
 * Generated entirely client-side from the /api/admissions/{subject}/{hadm}
 * payload that's already on screen, so the report can never disagree with the
 * dashboard it was exported from.
 *
 * The document uses its own fixed light palette rather than the app's theme
 * tokens: this is a printed clinical document, and it should look the same
 * whether the dashboard was in dark or light mode when it was exported.
 */
import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";

/* ── Print palette (independent of the on-screen theme) ── */
const INK = [15, 30, 43];
const MUTED = [91, 107, 123];
const RULE = [216, 224, 232];
const BRAND = [14, 124, 134];
const PANEL = [244, 247, 250];
const WHITE = [255, 255, 255];
const TONE = {
  critical: [185, 28, 28],
  abnormal: [180, 83, 9],
  normal: [4, 120, 87],
};
const CATEGORY_TONE = { High: TONE.critical, Medium: TONE.abnormal, Low: TONE.normal };

const PAGE = { w: 210, h: 297, margin: 16 };
const CONTENT_W = PAGE.w - PAGE.margin * 2;
const FOOT_H = 16; // reserved strip at the bottom of every page

const STATUS_LABEL = { normal: "Normal", abnormal: "Abnormal", critical: "Critical" };
const TREND_LABEL = { worsening: "Worsening", improving: "Improving", stable: "Stable" };

const fmtTime = (iso) => String(iso || "").replace("T", " ").slice(0, 16);
const num = (v) => (v == null ? "—" : (+v).toLocaleString());
/* Trim float noise the same way the dashboard does, so printed values match. */
const sig = (v) => (v == null ? "—" : String((+v).toPrecision(3) / 1));
const fmtHours = (h) => (h >= 48 ? `${(h / 24).toFixed(1)} days` : `${h} h`);

/* The same sentence the dashboard shows above the trajectory. */
function leadTimeSentence(lt) {
  if (!lt || !lt.deteriorated) return "No critically out-of-range value was reached during this stay.";
  if (!lt.concerned) return `A critical ${lt.event_lab} value appeared without the score escalating first.`;
  if (lt.lead_concern_hours > 0) {
    return `Risk flagged concern ${fmtHours(lt.lead_concern_hours)} before the first critical value (${lt.event_lab}).`;
  }
  return `Risk escalated at the same measurement as the first critical value (${lt.event_lab}).`;
}

/* ── Small layout helpers ───────────────────────────────────────────────── */

function makeCursor(doc) {
  let y = PAGE.margin;
  return {
    get y() { return y; },
    set y(v) { y = v; },
    /* Start a new page if `need` mm won't fit above the footer strip. */
    ensure(need) {
      if (y + need > PAGE.h - FOOT_H) {
        doc.addPage();
        y = PAGE.margin;
        return true;
      }
      return false;
    },
  };
}

function sectionTitle(doc, cur, text) {
  cur.ensure(14);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.setTextColor(...INK);
  doc.text(text.toUpperCase(), PAGE.margin, cur.y);
  cur.y += 2;
  doc.setDrawColor(...BRAND);
  doc.setLineWidth(0.6);
  doc.line(PAGE.margin, cur.y, PAGE.margin + 18, cur.y);
  cur.y += 5;
}

function paragraph(doc, cur, text, { size = 9, color = MUTED } = {}) {
  doc.setFont("helvetica", "normal");
  doc.setFontSize(size);
  doc.setTextColor(...color);
  const lines = doc.splitTextToSize(text, CONTENT_W);
  cur.ensure(lines.length * (size * 0.42) + 3);
  doc.text(lines, PAGE.margin, cur.y);
  cur.y += lines.length * (size * 0.42) + 3;
}

/* ── Header / identity ──────────────────────────────────────────────────── */

function drawHeader(doc, d, meta) {
  doc.setFillColor(...BRAND);
  doc.rect(0, 0, PAGE.w, 26, "F");

  doc.setFont("helvetica", "bold");
  doc.setFontSize(15);
  doc.setTextColor(...WHITE);
  doc.text("Patient Deterioration Report", PAGE.margin, 12);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  doc.text("Clinical Control · Deterioration Watch", PAGE.margin, 18.5);

  const stamp = `Generated ${new Date().toLocaleString()}`;
  doc.text(stamp, PAGE.w - PAGE.margin, 12, { align: "right" });
  doc.text("Station 4B-NC-01 · Dr. Smith", PAGE.w - PAGE.margin, 18.5, { align: "right" });

  return 26;
}

function drawIdentity(doc, cur, d, meta) {
  const cat = d.risk.category;
  const tone = CATEGORY_TONE[cat] || MUTED;
  const h = 26;

  doc.setFillColor(...PANEL);
  doc.roundedRect(PAGE.margin, cur.y, CONTENT_W, h, 2, 2, "F");
  /* Risk colour reads before any number does — same idea as the score card. */
  doc.setFillColor(...tone);
  doc.rect(PAGE.margin, cur.y, 1.6, h, "F");

  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  doc.setTextColor(...INK);
  doc.text(`Patient ${d.subject_id}`, PAGE.margin + 7, cur.y + 11);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.setTextColor(...MUTED);
  doc.text(`Admission ID ${d.hadm_id}`, PAGE.margin + 7, cur.y + 18);

  /* Score + category, right-aligned */
  const right = PAGE.margin + CONTENT_W - 7;
  doc.setFont("helvetica", "bold");
  doc.setFontSize(24);
  doc.setTextColor(...tone);
  doc.text(String(d.risk.score), right, cur.y + 13, { align: "right" });

  doc.setFontSize(9);
  const label = d.risk.pattern
    ? `${cat} risk · score ${d.risk.score} of ${d.risk.max_score}`
    : `${cat} risk`;
  doc.text(label.toUpperCase(), right, cur.y + 19.5, { align: "right" });

  cur.y += h + 6;
}

/* Four summary tiles: labs, critical, worsening, observation span. */
function drawMetrics(doc, cur, d, meta) {
  const contributions = d.risk.contributions || [];
  const nHigh = meta?.n_high ?? contributions.filter((c) => c.status === "critical").length;
  const nWorse = meta?.n_worsening ?? contributions.filter((c) => c.trend === "worsening").length;
  const nLabs = meta?.n_measurements ?? d.labs.reduce((s, l) => s + l.points.length, 0);
  const span = meta?.span_hours;

  const tiles = [
    ["Labs recorded", num(nLabs), MUTED],
    ["Critical labs", String(nHigh), nHigh > 0 ? TONE.critical : TONE.normal],
    ["Worsening", String(nWorse), nWorse > 0 ? TONE.abnormal : TONE.normal],
    ["Observation span", span != null ? `${span} h` : "—", MUTED],
  ];

  const gap = 3;
  const w = (CONTENT_W - gap * (tiles.length - 1)) / tiles.length;
  const h = 20;
  cur.ensure(h + 6);

  tiles.forEach(([label, value, tone], i) => {
    const x = PAGE.margin + i * (w + gap);
    doc.setFillColor(...WHITE);
    doc.setDrawColor(...RULE);
    doc.setLineWidth(0.3);
    doc.roundedRect(x, cur.y, w, h, 1.5, 1.5, "FD");

    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    doc.setTextColor(...MUTED);
    doc.text(label.toUpperCase(), x + 4, cur.y + 6.5);

    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.setTextColor(...tone);
    doc.text(value, x + 4, cur.y + 15.5);
  });

  cur.y += h + 8;
}

/* ── Risk trajectory, drawn as vector so it stays crisp at any zoom ────── */

function drawTrajectory(doc, cur, d) {
  const traj = (d.trajectory || [])
    .map((t) => ({ ts: new Date(t.time).getTime(), score: +t.score }))
    .filter((t) => Number.isFinite(t.ts) && Number.isFinite(t.score));
  if (traj.length < 2) return; // nothing meaningful to plot

  const h = 46;
  const padL = 12, padR = 4, padT = 4, padB = 9;
  cur.ensure(h + 8);

  const x0 = PAGE.margin, y0 = cur.y;
  doc.setFillColor(...WHITE);
  doc.setDrawColor(...RULE);
  doc.setLineWidth(0.3);
  doc.roundedRect(x0, y0, CONTENT_W, h, 1.5, 1.5, "FD");

  const plotX = x0 + padL, plotY = y0 + padT;
  const plotW = CONTENT_W - padL - padR, plotH = h - padT - padB;

  const tsMin = traj[0].ts, tsMax = traj[traj.length - 1].ts;
  const tsSpan = tsMax - tsMin || 1;
  const maxScore = Math.max(1, ...traj.map((t) => t.score));
  const yTop = Math.ceil(maxScore * 1.15);

  const px = (ts) => plotX + ((ts - tsMin) / tsSpan) * plotW;
  const py = (s) => plotY + plotH - (s / yTop) * plotH;

  // Horizontal gridlines + y labels
  doc.setFontSize(6);
  doc.setFont("helvetica", "normal");
  for (let i = 0; i <= 3; i++) {
    const v = (yTop / 3) * i;
    const y = py(v);
    doc.setDrawColor(...RULE);
    doc.setLineWidth(0.2);
    doc.line(plotX, y, plotX + plotW, y);
    doc.setTextColor(...MUTED);
    doc.text(String(Math.round(v)), plotX - 2, y + 1.2, { align: "right" });
  }

  // stepAfter line — a lab value holds until the next reading, matching the app
  doc.setDrawColor(...BRAND);
  doc.setLineWidth(0.7);
  for (let i = 0; i < traj.length - 1; i++) {
    const a = traj[i], b = traj[i + 1];
    doc.line(px(a.ts), py(a.score), px(b.ts), py(a.score));
    doc.line(px(b.ts), py(a.score), px(b.ts), py(b.score));
  }

  // Lead-time markers
  const lt = d.lead_time || {};
  const marker = (iso, tone, label) => {
    if (!iso) return;
    const ts = new Date(iso).getTime();
    if (!Number.isFinite(ts) || ts < tsMin || ts > tsMax) return;
    const x = px(ts);
    doc.setDrawColor(...tone);
    doc.setLineWidth(0.4);
    doc.setLineDashPattern([1, 1], 0);
    doc.line(x, plotY, x, plotY + plotH);
    doc.setLineDashPattern([], 0);
    doc.setFontSize(5.5);
    doc.setTextColor(...tone);
    doc.text(label, x + 1, plotY + 3);
  };
  marker(lt.concern_time, TONE.abnormal, "concern");
  if (lt.event_time !== lt.concern_time) marker(lt.event_time, TONE.critical, "critical");

  // x-axis endpoints
  doc.setFontSize(6);
  doc.setTextColor(...MUTED);
  doc.text(fmtTime(new Date(tsMin).toISOString()), plotX, y0 + h - 3);
  doc.text(fmtTime(new Date(tsMax).toISOString()), plotX + plotW, y0 + h - 3, { align: "right" });

  cur.y += h + 6;
}

/* ── Tables ─────────────────────────────────────────────────────────────── */

const TABLE_BASE = {
  margin: { left: PAGE.margin, right: PAGE.margin, bottom: FOOT_H },
  styles: { font: "helvetica", fontSize: 8, cellPadding: 2, textColor: INK, lineColor: RULE, lineWidth: 0.2 },
  headStyles: { fillColor: PANEL, textColor: INK, fontStyle: "bold", fontSize: 7.5 },
  alternateRowStyles: { fillColor: [250, 252, 253] },
};

function drawFactors(doc, cur, d) {
  const drivers = (d.risk.contributions || []).filter((c) => c.points > 0);
  sectionTitle(doc, cur, "Why this score");

  if (!drivers.length) {
    paragraph(doc, cur, "All labs are within their normal range — nothing is driving up the risk score.");
    cur.y += 2;
    return;
  }

  autoTable(doc, {
    ...TABLE_BASE,
    startY: cur.y,
    head: [["Indicator", "Latest value", "Status", "Trend", "Points"]],
    body: drivers.map((c) => [
      c.test_name,
      `${sig(c.latest_value)} ${c.unit || ""}`.trim(),
      STATUS_LABEL[c.status] || c.status,
      TREND_LABEL[c.trend] || c.trend,
      `+${c.points}`,
    ]),
    columnStyles: {
      1: { halign: "right" },
      4: { halign: "center", fontStyle: "bold" },
    },
    /* Colour the status and points cells by severity, like the on-screen table. */
    didParseCell: (data) => {
      if (data.section !== "body") return;
      const tone = TONE[drivers[data.row.index].status];
      if (tone && (data.column.index === 2 || data.column.index === 4)) {
        data.cell.styles.textColor = tone;
        data.cell.styles.fontStyle = "bold";
      }
      if (data.column.index === 3 && drivers[data.row.index].trend === "worsening") {
        data.cell.styles.textColor = TONE.critical;
      }
    },
  });
  cur.y = doc.lastAutoTable.finalY + 7;
}

function drawAlerts(doc, cur, d) {
  const alerts = d.alerts || [];
  sectionTitle(doc, cur, "Early-warning alerts");

  if (!alerts.length) {
    paragraph(doc, cur, "No alerts — all labs within range.");
    cur.y += 2;
    return;
  }

  alerts.forEach((a) => {
    const tone = a.level === "high" ? TONE.critical : TONE.abnormal;
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    const lines = doc.splitTextToSize(a.message, CONTENT_W - 8);
    const h = Math.max(7, lines.length * 4 + 3);
    cur.ensure(h + 2);

    doc.setFillColor(...PANEL);
    doc.rect(PAGE.margin, cur.y, CONTENT_W, h, "F");
    doc.setFillColor(...tone);
    doc.rect(PAGE.margin, cur.y, 1.2, h, "F");
    doc.setTextColor(...INK);
    doc.text(lines, PAGE.margin + 4, cur.y + 4.6);
    cur.y += h + 2;
  });
  cur.y += 5;
}

function drawSyndromes(doc, cur, d) {
  const syndromes = d.syndromes || [];
  if (!syndromes.length) return;

  sectionTitle(doc, cur, "Clinical syndromes detected");
  autoTable(doc, {
    ...TABLE_BASE,
    startY: cur.y,
    head: [["Pattern", "Severity", "Matched signals", "Interpretation"]],
    body: syndromes.map((s) => [
      s.name + (s.custom ? " (custom)" : ""),
      s.severity === "critical" ? "Critical" : "Warning",
      (s.matched || []).map((m) => `${m.test_name} ${sig(m.value)}`).join(", ") || "—",
      s.plain || "",
    ]),
    columnStyles: {
      0: { cellWidth: 34, fontStyle: "bold" },
      1: { cellWidth: 17, halign: "center" },
      2: { cellWidth: 45 },
    },
    didParseCell: (data) => {
      if (data.section === "body" && data.column.index === 1) {
        data.cell.styles.textColor =
          syndromes[data.row.index].severity === "critical" ? TONE.critical : TONE.abnormal;
        data.cell.styles.fontStyle = "bold";
      }
    },
  });
  cur.y = doc.lastAutoTable.finalY + 7;
}

function drawLabs(doc, cur, d) {
  const labs = d.labs || [];
  if (!labs.length) return;
  const byId = Object.fromEntries((d.risk.contributions || []).map((c) => [c.itemid, c]));

  sectionTitle(doc, cur, "Lab results");
  const rows = labs.map((lab) => {
    const info = byId[lab.itemid];
    const latest = lab.points.length ? lab.points[lab.points.length - 1] : null;
    return {
      status: info?.status || "normal",
      cells: [
        lab.test_name,
        latest ? `${sig(latest.value)} ${lab.unit || ""}`.trim() : "—",
        `${lab.normal_low}–${lab.normal_high} ${lab.unit || ""}`.trim(),
        STATUS_LABEL[info?.status] || "Normal",
        TREND_LABEL[info?.trend] || "Stable",
        String(lab.points.length),
        latest ? fmtTime(latest.time) : "—",
      ],
    };
  });

  autoTable(doc, {
    ...TABLE_BASE,
    startY: cur.y,
    head: [["Test", "Latest", "Normal range", "Status", "Trend", "n", "Last measured"]],
    body: rows.map((r) => r.cells),
    columnStyles: {
      1: { halign: "right" },
      5: { halign: "center" },
      6: { cellWidth: 26 },
    },
    didParseCell: (data) => {
      if (data.section === "body" && data.column.index === 3) {
        data.cell.styles.textColor = TONE[rows[data.row.index].status] || INK;
        data.cell.styles.fontStyle = "bold";
      }
    },
  });
  cur.y = doc.lastAutoTable.finalY + 7;
}

/* ── Footer ─────────────────────────────────────────────────────────────── */

function drawFooters(doc, d) {
  const total = doc.getNumberOfPages();
  for (let i = 1; i <= total; i++) {
    doc.setPage(i);
    doc.setDrawColor(...RULE);
    doc.setLineWidth(0.3);
    doc.line(PAGE.margin, PAGE.h - 12, PAGE.w - PAGE.margin, PAGE.h - 12);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(7);
    doc.setTextColor(...MUTED);
    doc.text(
      "Research prototype — generated from MIMIC-III LABEVENTS. Not for clinical use.",
      PAGE.margin, PAGE.h - 8,
    );
    doc.text(
      `Patient ${d.subject_id} · Admission ${d.hadm_id} · Page ${i} of ${total}`,
      PAGE.w - PAGE.margin, PAGE.h - 8, { align: "right" },
    );
  }
}

/* ── Entry point ────────────────────────────────────────────────────────── */

/**
 * Build the report for one admission and hand it to the browser as a download.
 * Returns the filename written.
 */
export function downloadPatientReport({ d, meta }) {
  if (!d) throw new Error("No patient loaded");

  const doc = new jsPDF({ unit: "mm", format: "a4", compress: true });
  doc.setProperties({
    title: `Patient ${d.subject_id} — Deterioration Report`,
    subject: `Admission ${d.hadm_id}`,
    creator: "Clinical Control · Deterioration Watch",
  });

  const cur = makeCursor(doc);
  cur.y = drawHeader(doc, d, meta) + 8;

  drawIdentity(doc, cur, d, meta);
  drawMetrics(doc, cur, d, meta);

  sectionTitle(doc, cur, "Risk trajectory");
  paragraph(doc, cur, leadTimeSentence(d.lead_time), { color: INK });
  drawTrajectory(doc, cur, d);

  if (d.risk.pattern) {
    paragraph(doc, cur,
      `Scored by the custom pattern "${d.risk.pattern_name}" — only that pattern's labs `
      + "count toward this score, and only when they move the way the pattern specifies.");
  }

  drawFactors(doc, cur, d);
  drawAlerts(doc, cur, d);
  drawSyndromes(doc, cur, d);
  drawLabs(doc, cur, d);
  drawFooters(doc, d);

  const filename = `patient-${d.subject_id}-admission-${d.hadm_id}-report.pdf`;
  doc.save(filename);
  return filename;
}
