"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  MonitorConfig,
  MonitorStatus,
  fetchMonitorConfig,
  updateMonitorConfig,
  fetchMonitorStatus,
  startMonitoring,
  stopMonitoring,
  testNotification,
} from "@/lib/monitor-api";

// ---------------------------------------------------------------------------
// useCountdown — syncs to server value, ticks locally every second
// ---------------------------------------------------------------------------

function useCountdown(serverSeconds: number | null | undefined): number | null {
  const anchorRef = useRef<{ serverVal: number; receivedAt: number } | null>(null);
  const [display, setDisplay] = useState<number | null>(null);

  useEffect(() => {
    if (serverSeconds == null) {
      anchorRef.current = null;
      setDisplay(null);
      return;
    }
    anchorRef.current = { serverVal: serverSeconds, receivedAt: performance.now() / 1000 };
    setDisplay(serverSeconds);
  }, [serverSeconds]);

  useEffect(() => {
    const iv = setInterval(() => {
      const a = anchorRef.current;
      if (!a) { setDisplay(null); return; }
      const elapsed = performance.now() / 1000 - a.receivedAt;
      setDisplay(Math.max(0, Math.round(a.serverVal - elapsed)));
    }, 1000);
    return () => clearInterval(iv);
  }, []);

  return display;
}

function useTimeAgo(unixTs: number): string {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!unixTs) return;
    const iv = setInterval(() => setTick((t) => t + 1), 5000);
    return () => clearInterval(iv);
  }, [unixTs]);
  if (!unixTs) return "never";
  const s = Math.floor(Date.now() / 1000 - unixTs);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

// ---------------------------------------------------------------------------
// Shared hook
// ---------------------------------------------------------------------------

export interface MonitorState { config: MonitorConfig | null; status: MonitorStatus | null; }

export function useMonitorState(): MonitorState & { reload: () => Promise<void> } {
  const [config, setConfig] = useState<MonitorConfig | null>(null);
  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const reload = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([fetchMonitorConfig(), fetchMonitorStatus()]);
      setConfig(c); setStatus(s);
    } catch { /* */ }
  }, []);
  useEffect(() => { reload(); const iv = setInterval(reload, 10000); return () => clearInterval(iv); }, [reload]);
  return { config, status, reload };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCountdown(s: number | null): string {
  if (s == null || s <= 0) return "scanning...";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60); const r = s % 60;
  return r > 0 ? `${m}m ${r}s` : `${m}m`;
}

const PRESETS = [
  { value: "conservative", label: "Conservative", desc: "8% EV, 30m refresh, 1hr cooldown" },
  { value: "standard", label: "Standard", desc: "5% EV, 15m refresh, 30m cooldown" },
  { value: "aggressive", label: "Aggressive", desc: "3% EV, 10m refresh, 15m cooldown" },
];

const iStyle = { background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" };
const iClass = "rounded border font-mono text-[11px] focus:outline-none focus:border-[rgba(45,212,191,0.5)]";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props { config: MonitorConfig | null; status: MonitorStatus | null; onReload: () => Promise<void>; }

export function NotificationSettings({ config, status, onReload }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [testState, setTestState] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);

  const poller = status?.odds_poller as Record<string, number | null> | undefined;
  const serverNext = poller?.seconds_until_next ?? null;
  const refreshMin = poller?.interval_minutes ?? config?.refresh_interval_minutes ?? 15;
  const pollsMax = poller?.max_polls_per_day ?? 20;
  const pollsRemaining = poller?.polls_remaining ?? pollsMax;
  const eventCount = poller?.latest_event_count ?? 0;
  const lastPollTs = (poller?.last_poll as number) ?? 0;

  const countdown = useCountdown(serverNext);
  const lastScanAgo = useTimeAgo(lastPollTs);

  const running = status?.running ?? false;
  const totalSent = status?.total_alerts_sent ?? 0;
  const totalCycles = status?.total_cycles ?? 0;
  const lastCycle = status?.last_cycle_result as Record<string, number> | null;

  if (!config) return null;

  const save = async (updates: Record<string, unknown>) => {
    setSaving(true); setError(null);
    try { await updateMonitorConfig(updates); await onReload(); }
    finally { setSaving(false); }
  };

  const handleStartStop = async () => {
    setStarting(true); setError(null);
    try {
      if (running) { await stopMonitoring(); }
      else { await startMonitoring(); }
      await onReload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally { setStarting(false); }
  };

  const handleTest = async () => {
    setTestState("sending"); setError(null);
    try {
      const r = await testNotification();
      setTestState(r.sent ? "sent" : "failed");
    } catch (e: unknown) {
      setTestState("failed");
      setError(e instanceof Error ? e.message : "Failed");
    }
    setTimeout(() => setTestState("idle"), 4000);
  };

  const countdownColor = countdown == null ? "#374151" : countdown <= 0 ? "#2dd4bf" : countdown <= 30 ? "#f59e0b" : "#6b7280";

  return (
    <div className="rounded-lg border" style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}>
      {/* ── COLLAPSED BAR ── */}
      <div className="flex items-center justify-between px-4 py-2 cursor-pointer select-none" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] tracking-[0.12em] uppercase font-medium" style={{ color: running ? "#2dd4bf" : "#4b5563" }}>
            Phone Alerts
          </span>
          {running && config.preset !== "custom" && (
            <span className="font-mono text-[8px] tracking-wider px-1.5 py-0.5 rounded-md border uppercase"
              style={{ color: "#2dd4bf", background: "rgba(45,212,191,0.06)", borderColor: "rgba(45,212,191,0.2)" }}>
              {config.preset}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 font-mono text-[9px]" style={{ color: "#374151" }}>
          {running && countdown != null && (
            <>
              <span>Next scan <span style={{ color: countdownColor, fontVariantNumeric: "tabular-nums" }}>{fmtCountdown(countdown)}</span></span>
              <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
              <span>{(config.min_ev * 100).toFixed(0)}%+ EV</span>
              <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
            </>
          )}
          {totalSent > 0 && <><span>{totalSent} sent</span><div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} /></>}
          {running ? (
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#4ade80", boxShadow: "0 0 4px #4ade80" }} />
              <span>Live</span>
            </div>
          ) : (
            <span style={{ color: "#374151" }}>Off</span>
          )}
          <span style={{ color: "#1f3a3d" }}>{expanded ? "\u25B2" : "\u25BC"}</span>
        </div>
      </div>

      {/* ── EXPANDED ── */}
      {expanded && (
        <div className="px-4 pb-4 space-y-4" style={{ borderTop: "1px solid rgba(19,78,74,0.2)" }}>

          {/* Start / Stop button */}
          <div className="pt-3 flex items-center gap-3">
            <button
              onClick={handleStartStop}
              disabled={starting}
              className="px-5 py-2 rounded-md border font-mono text-[11px] font-semibold tracking-wider uppercase transition-all"
              style={running ? {
                color: "#ef4444", background: "rgba(239,68,68,0.06)", borderColor: "rgba(239,68,68,0.25)",
              } : {
                color: "#2dd4bf", background: "rgba(45,212,191,0.06)", borderColor: "rgba(45,212,191,0.25)",
              }}
            >
              {starting ? "..." : running ? "Stop Monitoring" : "Start Monitoring"}
            </button>
            {error && <span className="font-mono text-[9px]" style={{ color: "#ef4444" }}>{error}</span>}
            {!config.has_pushover_credentials && !running && (
              <span className="font-mono text-[9px]" style={{ color: "#f59e0b" }}>
                Set PUSHOVER keys in .env first
              </span>
            )}
          </div>

          {/* Live dashboard — only when running */}
          {running && (
            <div className="grid grid-cols-5 gap-3">
              <div className="rounded-md border px-3 py-2" style={{ borderColor: "rgba(19,78,74,0.2)", background: "rgba(13,20,22,0.5)" }}>
                <div className="font-mono text-[8px] uppercase tracking-wider" style={{ color: "#4b5563" }}>Next Scan</div>
                <div className="font-mono text-[14px] font-bold mt-0.5" style={{ color: countdownColor, fontVariantNumeric: "tabular-nums" }}>
                  {fmtCountdown(countdown)}
                </div>
                <div className="font-mono text-[8px] mt-0.5" style={{ color: "#374151" }}>every {refreshMin}m</div>
              </div>
              <div className="rounded-md border px-3 py-2" style={{ borderColor: "rgba(19,78,74,0.2)", background: "rgba(13,20,22,0.5)" }}>
                <div className="font-mono text-[8px] uppercase tracking-wider" style={{ color: "#4b5563" }}>API Budget</div>
                <div className="font-mono text-[14px] font-bold mt-0.5" style={{ color: pollsRemaining <= 3 ? "#ef4444" : pollsRemaining <= 10 ? "#f59e0b" : "#e2e8f0", fontVariantNumeric: "tabular-nums" }}>
                  {pollsRemaining}/{pollsMax}
                </div>
                <div className="font-mono text-[8px] mt-0.5" style={{ color: "#374151" }}>polls left today</div>
              </div>
              <div className="rounded-md border px-3 py-2" style={{ borderColor: "rgba(19,78,74,0.2)", background: "rgba(13,20,22,0.5)" }}>
                <div className="font-mono text-[8px] uppercase tracking-wider" style={{ color: "#4b5563" }}>FD Events</div>
                <div className="font-mono text-[14px] font-bold mt-0.5" style={{ color: "#e2e8f0", fontVariantNumeric: "tabular-nums" }}>{eventCount}</div>
                <div className="font-mono text-[8px] mt-0.5" style={{ color: "#374151" }}>scanned {lastScanAgo}</div>
              </div>
              <div className="rounded-md border px-3 py-2" style={{ borderColor: "rgba(19,78,74,0.2)", background: "rgba(13,20,22,0.5)" }}>
                <div className="font-mono text-[8px] uppercase tracking-wider" style={{ color: "#4b5563" }}>Alerts Sent</div>
                <div className="font-mono text-[14px] font-bold mt-0.5" style={{ color: totalSent > 0 ? "#a78bfa" : "#374151", fontVariantNumeric: "tabular-nums" }}>{totalSent}</div>
                <div className="font-mono text-[8px] mt-0.5" style={{ color: "#374151" }}>{totalCycles} scans</div>
              </div>
              <div className="rounded-md border px-3 py-2" style={{ borderColor: "rgba(19,78,74,0.2)", background: "rgba(13,20,22,0.5)" }}>
                <div className="font-mono text-[8px] uppercase tracking-wider" style={{ color: "#4b5563" }}>Last Scan</div>
                {lastCycle ? (
                  <div className="flex flex-col gap-0.5 mt-1 font-mono text-[9px]">
                    <span style={{ color: "#6b7280" }}>{lastCycle.candidates_evaluated ?? 0} evaluated</span>
                    <span style={{ color: "#6b7280" }}>{lastCycle.filter_passed ?? 0} qualified</span>
                    <span style={{ color: (lastCycle.alerts_sent ?? 0) > 0 ? "#a78bfa" : "#6b7280" }}>{lastCycle.alerts_sent ?? 0} alerted</span>
                  </div>
                ) : (
                  <div className="font-mono text-[9px] mt-1" style={{ color: "#374151" }}>waiting...</div>
                )}
              </div>
            </div>
          )}

          {/* ── Preset selector ── */}
          <div>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-2" style={{ color: "#4b5563" }}>Preset</div>
            <div className="flex gap-2">
              {PRESETS.map((p) => {
                const active = config.preset === p.value;
                return (
                  <button key={p.value} onClick={() => save({ preset: p.value })} disabled={saving}
                    className="flex-1 px-3 py-2 rounded-md border text-left transition-all"
                    style={{ background: active ? "rgba(45,212,191,0.06)" : "transparent", borderColor: active ? "rgba(45,212,191,0.25)" : "rgba(75,85,99,0.12)" }}>
                    <div className="font-mono text-[10px] font-semibold" style={{ color: active ? "#2dd4bf" : "#6b7280" }}>{p.label}</div>
                    <div className="font-mono text-[8px] mt-0.5 leading-relaxed" style={{ color: "#374151" }}>{p.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Settings ── */}
          <div>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-2" style={{ color: "#4b5563" }}>Settings</div>
            <div className="grid grid-cols-4 gap-x-4 gap-y-2">
              <div className="space-y-1">
                <label className="font-mono text-[9px]" style={{ color: "#4b5563" }}>Min EV</label>
                <div className="relative">
                  <input type="number" step="1" min="1" max="50"
                    value={Math.round(config.min_ev * 100)}
                    onChange={(e) => save({ min_ev: parseFloat(e.target.value) / 100 })}
                    className={`w-full pl-2 pr-5 py-1 text-right ${iClass}`} style={iStyle} />
                  <span className="absolute right-1.5 top-1/2 -translate-y-1/2 font-mono text-[9px]" style={{ color: "#374151" }}>%</span>
                </div>
              </div>
              <div className="space-y-1">
                <label className="font-mono text-[9px]" style={{ color: "#4b5563" }}>Refresh every</label>
                <div className="relative">
                  <input type="number" step="5" min="5" max="60"
                    value={config.refresh_interval_minutes}
                    onChange={(e) => save({ refresh_interval_minutes: parseInt(e.target.value) || 15 })}
                    className={`w-full pl-2 pr-7 py-1 text-right ${iClass}`} style={iStyle} />
                  <span className="absolute right-1.5 top-1/2 -translate-y-1/2 font-mono text-[9px]" style={{ color: "#374151" }}>min</span>
                </div>
              </div>
              <div className="space-y-1">
                <label className="font-mono text-[9px]" style={{ color: "#4b5563" }}>Cooldown</label>
                <div className="relative">
                  <input type="number" step="5" min="5" max="120"
                    value={config.cooldown_minutes}
                    onChange={(e) => save({ cooldown_minutes: parseInt(e.target.value) || 30 })}
                    className={`w-full pl-2 pr-7 py-1 text-right ${iClass}`} style={iStyle} />
                  <span className="absolute right-1.5 top-1/2 -translate-y-1/2 font-mono text-[9px]" style={{ color: "#374151" }}>min</span>
                </div>
              </div>
              <div className="space-y-1">
                <label className="font-mono text-[9px]" style={{ color: "#4b5563" }}>Max alerts/hr</label>
                <input type="number" step="1" min="1" max="30"
                  value={config.max_alerts_per_hour}
                  onChange={(e) => save({ max_alerts_per_hour: parseInt(e.target.value) || 10 })}
                  className={`w-full px-2 py-1 text-right ${iClass}`} style={iStyle} />
              </div>
            </div>
          </div>

          {/* ── Platforms + dry run ── */}
          <div className="flex items-center gap-4">
            <span className="font-mono text-[9px]" style={{ color: "#4b5563" }}>Platforms</span>
            {["polymarket", "kalshi"].map((p) => (
              <label key={p} className="flex items-center gap-1 font-mono text-[10px] cursor-pointer"
                style={{ color: config.platforms.includes(p) ? "#e2e8f0" : "#4b5563" }}>
                <input type="checkbox" checked={config.platforms.includes(p)}
                  onChange={(e) => {
                    const next = e.target.checked ? [...config.platforms, p] : config.platforms.filter((x) => x !== p);
                    if (next.length > 0) save({ platforms: next });
                  }}
                  className="w-3 h-3 rounded accent-teal-400" />
                {p === "polymarket" ? "Polymarket" : "Kalshi"}
              </label>
            ))}
            <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
            <label className="flex items-center gap-1 font-mono text-[10px] cursor-pointer"
              style={{ color: config.dry_run ? "#f59e0b" : "#4b5563" }}>
              <input type="checkbox" checked={config.dry_run}
                onChange={(e) => save({ dry_run: e.target.checked })}
                className="w-3 h-3 rounded accent-amber-400" />
              Dry run
            </label>
          </div>

          {/* ── Footer ── */}
          <div className="flex items-center justify-between pt-2" style={{ borderTop: "1px solid rgba(19,78,74,0.12)" }}>
            <div className="font-mono text-[9px]" style={{ color: "#374151" }}>
              {config.has_pushover_credentials
                ? <span style={{ color: "#4b5563" }}>Pushover connected</span>
                : <span>Set PUSHOVER_USER_KEY + PUSHOVER_API_TOKEN in .env &mdash; <a href="https://pushover.net" target="_blank" rel="noopener noreferrer" style={{ color: "#4b5563", textDecoration: "underline" }}>pushover.net</a></span>
              }
            </div>
            <button onClick={handleTest}
              disabled={testState === "sending" || !config.has_pushover_credentials}
              className="px-3 py-1 rounded-md border font-mono text-[9px] tracking-wider uppercase transition-all"
              style={{
                color: testState === "sent" ? "#4ade80" : testState === "failed" ? "#ef4444" : !config.has_pushover_credentials ? "#1f3a3d" : "#6b7280",
                borderColor: testState === "sent" ? "rgba(74,222,128,0.3)" : testState === "failed" ? "rgba(239,68,68,0.3)" : "rgba(75,85,99,0.2)",
                background: testState === "sent" ? "rgba(74,222,128,0.06)" : testState === "failed" ? "rgba(239,68,68,0.06)" : "rgba(75,85,99,0.05)",
              }}>
              {testState === "sending" ? "Sending..." : testState === "sent" ? "Sent to phone" : testState === "failed" ? "Failed" : "Test Push"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
