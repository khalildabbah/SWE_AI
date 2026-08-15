/*
 * Single source of truth for the colours and chart styling that live in JS.
 *
 * Recharts styles its axes, grids and tooltips through inline props, so those
 * values can't read the CSS custom properties in styles.css. The two palettes
 * below mirror the `:root` (dark) and `:root[data-theme="light"]` token blocks
 * in that file — change one, change the other.
 *
 * Components read the active palette through `useChartTheme()`, so switching
 * theme re-renders every chart with the right colours.
 */
import { createContext, useContext, useMemo } from "react";

/* Mirrors the surface / text / accent tokens in styles.css. */
const PALETTE = {
  dark: {
    surface: "#131f2e",
    surfaceHigh: "#1a2938",
    surfaceLowest: "#070f19",
    border: "#243444",
    grid: "#1f2d3c",
    axis: "#7d8fa1",
    text: "#e4edf5",
    textMuted: "#a7b6c6",
    primary: "#5fc9d9",
    healthy: "#34d399",
    warning: "#fbbf24",
    critical: "#f87171",
    bandOpacity: 0.08,
  },
  light: {
    surface: "#ffffff",
    surfaceHigh: "#e9eff5",
    surfaceLowest: "#ffffff",
    border: "#dbe3ea",
    grid: "#e4eaf0",
    axis: "#63788c",
    text: "#0f1e2b",
    textMuted: "#44586b",
    primary: "#0e7c86",
    healthy: "#047857",
    warning: "#d97706",
    critical: "#dc2626",
    bandOpacity: 0.1,
  },
};

export const THEMES = Object.keys(PALETTE);
export const DEFAULT_THEME = "dark";

/* Active theme name ("dark" | "light"), provided by App. */
export const ThemeContext = createContext(DEFAULT_THEME);

const MONO = '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace';

/* Everything a chart needs, derived from one palette. */
function build(COLOR) {
  return {
    COLOR,

    /* Risk category → accent, used for the trajectory stroke/fill. */
    RISK_COLOR: {
      Low: COLOR.healthy,
      Medium: COLOR.warning,
      High: COLOR.critical,
    },

    /* Per-lab abnormality status → colour + label (matches src/analysis/abnormal.py). */
    STATUS: {
      normal: { color: COLOR.healthy, label: "Normal" },
      abnormal: { color: COLOR.warning, label: "Abnormal" },
      critical: { color: COLOR.critical, label: "Critical" },
    },

    /* Axis ticks: mono digits, muted, no axis rule — the grid carries the structure. */
    axisTick: (size = 10) => ({ fontSize: size, fill: COLOR.axis, fontFamily: MONO }),

    /* Shared axis props so every chart drops its axis/tick rules the same way. */
    AXIS_PROPS: { axisLine: false, tickLine: false },

    /* Grid: horizontal hairlines only, so the eye reads values not a graph-paper box. */
    GRID_PROPS: { stroke: COLOR.grid, strokeDasharray: "2 6", vertical: false },

    /* The healthy band drawn behind a lab sparkline. */
    NORMAL_BAND: { fill: COLOR.healthy, fillOpacity: COLOR.bandOpacity },

    /* Tooltip: a floating card that matches the panel styling in styles.css. */
    tooltipProps: (fontSize = 12) => ({
      contentStyle: {
        background: COLOR.surfaceLowest,
        border: `1px solid ${COLOR.border}`,
        borderRadius: 10,
        boxShadow: "0 12px 32px rgba(0, 0, 0, 0.18)",
        padding: "8px 12px",
        fontSize,
      },
      labelStyle: {
        color: COLOR.axis,
        fontSize: 11,
        fontWeight: 600,
        marginBottom: 4,
        fontFamily: MONO,
      },
      itemStyle: { color: COLOR.text, fontWeight: 600, padding: 0 },
      cursor: { stroke: COLOR.axis, strokeWidth: 1, strokeDasharray: "3 3", strokeOpacity: 0.5 },
    }),
  };
}

const BUILT = { dark: build(PALETTE.dark), light: build(PALETTE.light) };

/* The chart palette for the theme currently in effect. */
export function useChartTheme() {
  const mode = useContext(ThemeContext);
  return useMemo(() => BUILT[mode] || BUILT[DEFAULT_THEME], [mode]);
}
