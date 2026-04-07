"use client";

import { useState, useCallback, useEffect } from "react";
import { Opportunity, OpportunitiesResponse } from "@/lib/types";
import { fetchOpportunities } from "@/lib/api";
import { useTrackedPositions } from "@/lib/useTrackedPositions";
import { OpportunitiesTable } from "./OpportunitiesTable";
import { MarketDetailPanel } from "./MarketDetailPanel";
import { TrackedPositions } from "./TrackedPositions";
import { NotificationSettings, useMonitorState } from "./NotificationSettings";

interface Props {
  initialData: OpportunitiesResponse;
}

function timeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

export function DashboardClient({ initialData }: Props) {
  const [edgeInput, setEdgeInput] = useState("5");
  const [bankrollInput, setBankrollInput] = useState("1000");
  const [bankroll, setBankroll] = useState(1000);
  const [data, setData] = useState<OpportunitiesResponse>(initialData);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());
  const [, setTick] = useState(0);

  const { positions, isTaken, takePosition, closePosition, removePosition } =
    useTrackedPositions();

  const monitor = useMonitorState();

  // Tick every second so "Updated Xs ago" counts up live
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  const reload = useCallback(async (edge: number) => {
    setLoading(true);
    try {
      const result = await fetchOpportunities({
        min_edge: edge / 100,
        wide_market_min_edge: Math.max(edge, 8) / 100,
      });
      setData(result);
      setSelected(null);
      setLastRefreshed(new Date());
    } catch {
      // keep existing data on error
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const edge = parseFloat(edgeInput);
    const br = parseFloat(bankrollInput);
    if (!isNaN(edge) && edge >= 0 && edge <= 100) {
      reload(edge);
    }
    if (!isNaN(br) && br > 0) {
      setBankroll(br);
    }
  };

  const { opportunities } = data;
  const displayed = selected ?? opportunities[0] ?? null;
  const displayedIsTaken = displayed ? isTaken(displayed) : false;

  const buyCount = opportunities.filter((o) => o.status === "BUY").length;
  const watchCount = opportunities.filter((o) => o.status === "WATCH").length;
  const platforms = [...new Set(opportunities.map((o) => o.platform))];
  const openPositions = positions.filter((p) => p.status === "open").length;

  // Quota from last response
  const quotaRemaining = data.quota_remaining;

  // Monitor status for toolbar
  const monitorRunning = monitor.status?.running ?? false;
  const monitorEnabled = monitor.config?.enabled ?? false;
  const alertsSent = monitor.status?.total_alerts_sent ?? 0;

  return (
    <main className="max-w-[1600px] mx-auto px-6 py-5 space-y-3">
      {/* Toolbar */}
      <div
        className="flex items-center justify-between px-4 py-2.5 rounded-lg border"
        style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
      >
        <form onSubmit={handleSubmit} className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <label htmlFor="min-edge" className="font-mono text-[9px]" style={{ color: "#4b5563" }}>
              Min Edge
            </label>
            <div className="relative">
              <input
                id="min-edge"
                type="number"
                step="0.5"
                min="0"
                max="100"
                value={edgeInput}
                onChange={(e) => setEdgeInput(e.target.value)}
                className="w-14 pl-2 pr-5 py-1 rounded-md border font-mono text-[11px] text-right focus:outline-none focus:border-[rgba(45,212,191,0.5)]"
                style={{ background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" }}
              />
              <span className="absolute right-1.5 top-1/2 -translate-y-1/2 font-mono text-[9px]" style={{ color: "#374151" }}>%</span>
            </div>
          </div>

          <div className="h-3.5 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />

          <div className="flex items-center gap-1.5">
            <label htmlFor="bankroll" className="font-mono text-[9px]" style={{ color: "#4b5563" }}>
              Bankroll
            </label>
            <div className="relative">
              <span className="absolute left-2 top-1/2 -translate-y-1/2 font-mono text-[9px]" style={{ color: "#374151" }}>$</span>
              <input
                id="bankroll"
                type="number"
                step="100"
                min="0"
                value={bankrollInput}
                onChange={(e) => setBankrollInput(e.target.value)}
                className="w-20 pl-5 pr-2 py-1 rounded-md border font-mono text-[11px] text-right focus:outline-none focus:border-[rgba(45,212,191,0.5)]"
                style={{ background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" }}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="px-4 py-1 rounded-md border font-mono text-[10px] tracking-wider uppercase transition-all duration-150"
            style={{
              color: loading ? "#374151" : "#2dd4bf",
              background: loading ? "rgba(75,85,99,0.05)" : "rgba(45,212,191,0.06)",
              borderColor: loading ? "rgba(75,85,99,0.15)" : "rgba(45,212,191,0.2)",
            }}
          >
            {loading ? "..." : "Refresh"}
          </button>
        </form>

        <div className="flex items-center gap-4 font-mono text-[9px]" style={{ color: "#374151" }}>
          <span>
            {opportunities.length} results ({buyCount} buy, {watchCount} watch)
          </span>
          {openPositions > 0 && (
            <>
              <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
              <span style={{ color: "#f59e0b" }}>
                {openPositions} tracked
              </span>
            </>
          )}
          {quotaRemaining && (
            <>
              <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
              <span>{quotaRemaining} API req left</span>
            </>
          )}
          <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
          <span>
            {platforms.length > 0 ? platforms.map(p => p === "polymarket" ? "PM" : p === "kalshi" ? "Kalshi" : p).join(" + ") : "No platforms"}
          </span>
          {monitorEnabled && (
            <>
              <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
              <div className="flex items-center gap-1.5">
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{
                    background: monitorRunning ? "#a78bfa" : "#f59e0b",
                    boxShadow: monitorRunning ? "0 0 4px #a78bfa" : undefined,
                  }}
                />
                <span style={{ color: monitorRunning ? "#a78bfa" : "#f59e0b" }}>
                  Alerts {monitorRunning ? "on" : "paused"}
                </span>
                {alertsSent > 0 && (
                  <span style={{ color: "#374151" }}>({alertsSent})</span>
                )}
              </div>
            </>
          )}
          <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
          <div className="flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: loading ? "#f59e0b" : "#4ade80",
                boxShadow: loading ? "0 0 4px #f59e0b" : "0 0 4px #4ade80",
              }}
            />
            <span>{loading ? "Refreshing..." : `Updated ${timeAgo(lastRefreshed)}`}</span>
          </div>
        </div>
      </div>

      {/* Notification settings */}
      <NotificationSettings
        config={monitor.config}
        status={monitor.status}
        onReload={monitor.reload}
      />

      {/* Main grid: table + sidebar */}
      <div className="grid gap-3" style={{ gridTemplateColumns: "1fr 320px" }}>
        <div className="space-y-3">
          <OpportunitiesTable
            opportunities={opportunities}
            selectedId={displayed?.market_id}
            onSelect={(opp) => setSelected(opp)}
            bankroll={bankroll}
            isTaken={isTaken}
          />
        </div>
        <div className="space-y-3">
          <MarketDetailPanel
            opportunity={displayed}
            bankroll={bankroll}
            isTaken={displayedIsTaken}
            onTake={() => displayed && takePosition(displayed)}
          />
        </div>
      </div>

      {/* Tracked positions */}
      {positions.length > 0 && (
        <TrackedPositions
          positions={positions}
          onClose={closePosition}
          onRemove={removePosition}
        />
      )}
    </main>
  );
}
