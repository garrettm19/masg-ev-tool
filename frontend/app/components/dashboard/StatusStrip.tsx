"use client";

import { useEffect, useState } from "react";
import { StatusPill, type StatusPillTone } from "../ui/StatusPill";

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

interface PillSpec {
  label: string;
  value: string;
  tone?: StatusPillTone;
  pulse?: boolean;
  title?: string;
  detail?: string | null;
}

export function StatusStrip(props: StatusStripProps) {
  // Tick every second so elapsed counters and "X ago" stay live.
  const [, setTick] = useState(0);
  useEffect(() => {
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, []);

  // --- Scan pill ---
  let scanPill: PillSpec;
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
      tone: "warn",
      pulse: true,
      detail: props.refreshStartedAt ? `${fmtElapsed(props.refreshStartedAt)} elapsed` : null,
    };
  } else if (props.updatedAt) {
    scanPill = {
      label: "Scan",
      value: fmtAgo(props.updatedAt),
      tone: "success",
      detail:
        props.lastRefreshDuration != null
          ? `${props.lastRefreshDuration.toFixed(0)}s last scan`
          : null,
    };
  } else {
    scanPill = { label: "Scan", value: "Idle", tone: "muted" };
  }

  // --- Books pill ---
  const enabledBooks = Object.entries(props.platformEnabled)
    .filter(([, v]) => v)
    .map(([k]) => props.platformLabels[k] ?? k);
  let booksPill: PillSpec;
  if (enabledBooks.length === 0) {
    booksPill = {
      label: "Books",
      value: "None",
      tone: "danger",
      title: "Enable at least one book to scan",
    };
  } else if (props.platformEnabled.polymarket) {
    booksPill = {
      label: "Books",
      value: enabledBooks.join(" + "),
      tone: "warn",
      title: "Polymarket is opt-in; default is Kalshi-only",
      detail: "PM opt-in",
    };
  } else {
    booksPill = { label: "Books", value: enabledBooks.join(" + "), tone: "success" };
  }

  // --- Alerts pill ---
  let alertsPill: PillSpec;
  if (props.monitorRunning && !props.monitorDryRun) {
    alertsPill = {
      label: "Alerts",
      value: "LIVE",
      tone: "danger",
      pulse: true,
      title: "Live Pushover alerts are active",
      detail: props.monitorPreset ?? null,
    };
  } else if (props.monitorRunning && props.monitorDryRun) {
    alertsPill = {
      label: "Alerts",
      value: "Dry-run",
      tone: "warn",
      pulse: true,
      title: "Monitor running, payloads logged not sent",
      detail: props.monitorPreset ?? null,
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
  const propsPill: PillSpec = props.propsEnabled
    ? { label: "Props", value: "On", tone: "warn" }
    : { label: "Props", value: "Off", tone: "muted" };

  return (
    <div
      className="flex flex-wrap items-center gap-2 px-4 py-2.5 rounded-lg border"
      style={{
        background: "var(--bg-surface)",
        borderColor: "var(--border-default)",
      }}
    >
      <StatusPill {...scanPill} />
      <StatusPill {...booksPill} />
      <StatusPill {...alertsPill} />
      <StatusPill {...propsPill} />
      {props.monitorPreset && props.monitorMinEv != null && (
        <div
          className="ml-auto flex items-center gap-3 font-mono text-[9px]"
          style={{ color: "var(--fg-faint)" }}
          title="Active monitor preset settings"
        >
          <span>min EV {(props.monitorMinEv * 100).toFixed(1)}%</span>
          {props.monitorCooldownMin != null && (
            <span>· cooldown {props.monitorCooldownMin}m</span>
          )}
          {props.monitorMaxPerHour != null && (
            <span>· max {props.monitorMaxPerHour}/hr</span>
          )}
        </div>
      )}
    </div>
  );
}
