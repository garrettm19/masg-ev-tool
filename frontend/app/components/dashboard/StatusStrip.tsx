"use client";

import { useEffect, useState } from "react";

interface StatusStripProps {
  // Refresh state
  isRefreshing: boolean;
  refreshStartedAt: number | null;
  updatedAt: number | null;
  lastRefreshDuration: number | null;
  lastRefreshError: string | null;
  // Books
  platformEnabled: Record<string, boolean>;
  platformLabels: Record<string, string>;
  // Alerts
  monitorRunning: boolean;
  monitorEnabled: boolean;
  monitorDryRun: boolean;
  monitorPreset: string | null;
  monitorMinEv: number | null;
  monitorCooldownMin: number | null;
  monitorMaxPerHour: number | null;
  // Props
  propsEnabled: boolean;
}

function fmtAgo(unixSec: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - unixSec));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function fmtElapsed(startedAt: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  return `${s}s`;
}

interface PillProps {
  label: string;
  value: string;
  tone?: "neutral" | "active" | "warn" | "danger" | "ok" | "muted";
  pulse?: boolean;
  title?: string;
  detail?: string | null;
}

function Pill({ label, value, tone = "neutral", pulse = false, title, detail }: PillProps) {
  const tones: Record<string, { dot: string; text: string; bg: string; border: string }> = {
    neutral: { dot: "#64748b", text: "#94a3b8", bg: "rgba(100,116,139,0.06)", border: "rgba(100,116,139,0.2)" },
    active:  { dot: "#f59e0b", text: "#fbbf24", bg: "rgba(245,158,11,0.07)", border: "rgba(245,158,11,0.3)" },
    warn:    { dot: "#f59e0b", text: "#fbbf24", bg: "rgba(245,158,11,0.05)", border: "rgba(245,158,11,0.2)" },
    danger:  { dot: "#f87171", text: "#fca5a5", bg: "rgba(248,113,113,0.06)", border: "rgba(248,113,113,0.3)" },
    ok:      { dot: "#4ade80", text: "#86efac", bg: "rgba(74,222,128,0.05)", border: "rgba(74,222,128,0.2)" },
    muted:   { dot: "#374151", text: "#4b5563", bg: "rgba(55,65,81,0.05)", border: "rgba(55,65,81,0.2)" },
  };
  const t = tones[tone];
  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-md border"
      style={{ background: t.bg, borderColor: t.border }}
      title={title}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${pulse ? "animate-pulse" : ""}`}
        style={{ background: t.dot, boxShadow: pulse ? `0 0 6px ${t.dot}` : "none" }}
      />
      <span className="font-mono text-[8px] tracking-[0.18em] uppercase" style={{ color: "#4b5563" }}>
        {label}
      </span>
      <span className="font-mono text-[10px] font-semibold" style={{ color: t.text }}>
        {value}
      </span>
      {detail != null && detail !== "" && (
        <span className="font-mono text-[9px]" style={{ color: "#4b5563" }}>
          · {detail}
        </span>
      )}
    </div>
  );
}

export function StatusStrip(props: StatusStripProps) {
  // Tick every second so elapsed counters and "X ago" stay live.
  const [, setTick] = useState(0);
  useEffect(() => {
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, []);

  // --- Scan pill ---
  let scanPill: PillProps;
  if (props.lastRefreshError) {
    scanPill = {
      label: "Scan",
      value: "Error",
      tone: "danger",
      title: props.lastRefreshError,
      detail: props.updatedAt ? `last good ${fmtAgo(props.updatedAt)}` : null,
    };
  } else if (props.isRefreshing) {
    scanPill = {
      label: "Scan",
      value: "Refreshing",
      tone: "active",
      pulse: true,
      detail: props.refreshStartedAt ? `${fmtElapsed(props.refreshStartedAt)} elapsed` : null,
    };
  } else if (props.updatedAt) {
    scanPill = {
      label: "Scan",
      value: fmtAgo(props.updatedAt),
      tone: "ok",
      detail: props.lastRefreshDuration != null ? `${props.lastRefreshDuration.toFixed(0)}s last scan` : null,
    };
  } else {
    scanPill = { label: "Scan", value: "Idle", tone: "muted" };
  }

  // --- Books pill ---
  const enabledBooks = Object.entries(props.platformEnabled)
    .filter(([, v]) => v)
    .map(([k]) => props.platformLabels[k] ?? k);
  let booksPill: PillProps;
  if (enabledBooks.length === 0) {
    booksPill = { label: "Books", value: "None", tone: "danger", title: "Enable at least one book to scan" };
  } else if (props.platformEnabled.polymarket) {
    booksPill = {
      label: "Books",
      value: enabledBooks.join(" + "),
      tone: "warn",
      title: "Polymarket is opt-in; default is Kalshi-only",
      detail: "PM opt-in",
    };
  } else {
    booksPill = { label: "Books", value: enabledBooks.join(" + "), tone: "ok" };
  }

  // --- Alerts pill ---
  let alertsPill: PillProps;
  if (props.monitorRunning && !props.monitorDryRun) {
    alertsPill = {
      label: "Alerts",
      value: "LIVE",
      tone: "danger",
      pulse: true,
      title: "Live Pushover alerts are active",
      detail: props.monitorPreset ? props.monitorPreset : null,
    };
  } else if (props.monitorRunning && props.monitorDryRun) {
    alertsPill = {
      label: "Alerts",
      value: "Dry-run",
      tone: "warn",
      pulse: true,
      title: "Monitor running, payloads logged not sent",
      detail: props.monitorPreset ? props.monitorPreset : null,
    };
  } else if (props.monitorDryRun) {
    alertsPill = {
      label: "Alerts",
      value: "Off (dry-run)",
      tone: "muted",
      title: "Monitor stopped; would dry-run if started",
    };
  } else {
    alertsPill = {
      label: "Alerts",
      value: "Off",
      tone: "muted",
      title: "Monitor stopped",
    };
  }

  // --- Props pill ---
  const propsPill: PillProps = props.propsEnabled
    ? { label: "Props", value: "On", tone: "warn" }
    : { label: "Props", value: "Off", tone: "muted" };

  return (
    <div
      className="flex flex-wrap items-center gap-2 px-4 py-2.5 rounded-lg border"
      style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
    >
      <Pill {...scanPill} />
      <Pill {...booksPill} />
      <Pill {...alertsPill} />
      <Pill {...propsPill} />
      {props.monitorPreset && props.monitorMinEv != null && (
        <div
          className="ml-auto flex items-center gap-3 font-mono text-[9px]"
          style={{ color: "#4b5563" }}
          title="Active monitor preset settings"
        >
          <span>min EV {(props.monitorMinEv * 100).toFixed(1)}%</span>
          {props.monitorCooldownMin != null && <span>· cooldown {props.monitorCooldownMin}m</span>}
          {props.monitorMaxPerHour != null && <span>· max {props.monitorMaxPerHour}/hr</span>}
        </div>
      )}
    </div>
  );
}
