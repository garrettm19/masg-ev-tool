"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Opportunity, OpportunitiesResponse } from "@/lib/types";
import { fetchSnapshotStatus, fetchSnapshot, refreshOpportunities, fetchSportsRegistry } from "@/lib/api";
import { startMonitoring, stopMonitoring } from "@/lib/monitor-api";
import { sportLabel, marketTypeLabel, isPropType, SportRegistryEntry } from "@/lib/sport-labels";
import { useTrackedPositions } from "@/lib/useTrackedPositions";
import { OpportunitiesTable } from "./OpportunitiesTable";
import { MarketDetailPanel } from "./MarketDetailPanel";
import { TrackedPositions } from "./TrackedPositions";
import { NotificationSettings, useMonitorState } from "./NotificationSettings";
import { DataStatus } from "./DataStatus";

interface Props {
  initialData: OpportunitiesResponse | null;
}

const EMPTY_DATA: OpportunitiesResponse = {
  opportunities: [],
  total: 0,
  status_counts: {},
  quota_remaining: null,
  sportsbook_markets_fetched: [],
  markets_dropped_by_type: {},
  platforms_fetched: [],
  updated_at: null,
  is_refreshing: false,
};

function timeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

// Stable key for matching an opportunity across data updates
function oppKey(o: Opportunity): string {
  return `${o.platform}:${o.market_id}:${o.side}`;
}

export function DashboardClient({ initialData }: Props) {
  const init = initialData ?? EMPTY_DATA;
  const [edgeInput, setEdgeInput] = useState("5");
  const [bankrollInput, setBankrollInput] = useState("1000");
  const [bankroll, setBankroll] = useState(1000);
  const [data, setData] = useState<OpportunitiesResponse>(init);
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(init.updated_at ?? null);
  const [backendRefreshing, setBackendRefreshing] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [, setTick] = useState(0);
  const lastSeenUpdatedAt = useRef<number | null>(init.updated_at ?? null);
  const pollIntervalRef = useRef(initialData ? 10_000 : 2_000); // fast poll if no initial data

  const { positions, isTaken, takePosition, closePosition, removePosition } =
    useTrackedPositions();

  const monitor = useMonitorState();

  // Sport registry — fetched once, used for labels everywhere
  const [sportsRegistry, setSportsRegistry] = useState<Record<string, SportRegistryEntry> | undefined>(undefined);
  useEffect(() => {
    fetchSportsRegistry().then(setSportsRegistry).catch(() => {});
  }, []);

  // Tick every second so "Updated Xs ago" counts up live
  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  // --- Snapshot polling: check /status, fetch /snapshot when updated_at changes ---
  // Polls at 2s while scanning (fast feedback), 10s otherwise (low overhead).
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const status = await fetchSnapshotStatus();
        if (!active) return;
        setBackendRefreshing(status.is_refreshing);

        if (
          status.has_snapshot &&
          status.updated_at != null &&
          status.updated_at !== lastSeenUpdatedAt.current
        ) {
          const snap = await fetchSnapshot();
          if (!active || !snap) return;
          lastSeenUpdatedAt.current = status.updated_at;
          setUpdatedAt(status.updated_at);
          setData((prev) => {
            if (selected) {
              const key = oppKey(selected);
              const match = snap.opportunities.find((o) => oppKey(o) === key);
              if (match) setSelected(match);
            }
            return snap;
          });

          // Scan delivered results — stop fast polling
          if (scanning) {
            setScanning(false);
            pollIntervalRef.current = 10_000;
          }
        }

        // If backend finished refreshing and we were scanning, stop
        if (scanning && !status.is_refreshing && status.has_snapshot) {
          // The snapshot may already have been picked up above.
          // If not (same updated_at), the scan produced no change — still stop.
          setScanning(false);
          pollIntervalRef.current = 10_000;
        }
      } catch {
        // Polling failure is silent — next tick will retry
      }
      if (active) timer = setTimeout(poll, pollIntervalRef.current);
    };

    timer = setTimeout(poll, pollIntervalRef.current);
    return () => { active = false; clearTimeout(timer); };
  }, [selected, scanning]);

  // --- Run Scan: fire POST /refresh, switch to fast polling, let polling deliver results ---
  const runScan = useCallback(() => {
    if (scanning) return;
    setScanning(true);
    pollIntervalRef.current = 2_000; // fast polling while scan runs
    refreshOpportunities().catch(() => {
      // If the POST itself fails, stop scanning state
      setScanning(false);
      pollIntervalRef.current = 10_000;
    });
  }, [scanning]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const br = parseFloat(bankrollInput);
    if (!isNaN(br) && br > 0) {
      setBankroll(br);
    }
    runScan();
  };

  // --- Client-side filters ---
  const [filterStatus, setFilterStatus] = useState<"all" | "BUY" | "WATCH">("all");
  const [filterPlatform, setFilterPlatform] = useState<string>("all");
  const [filterSport, setFilterSport] = useState<string>("all");
  const [filterMarketType, setFilterMarketType] = useState<string>("all");
  const [filterSearch, setFilterSearch] = useState("");

  const { opportunities: allOpps } = data;

  // Derive available filter options from all opportunities
  const availablePlatforms = useMemo(() => [...new Set(allOpps.map((o) => o.platform))].sort(), [allOpps]);
  const availableSports = useMemo(() => [...new Set(allOpps.map((o) => o.sport))].sort(), [allOpps]);
  const availableMarketTypes = useMemo(() => [...new Set(allOpps.map((o) => o.market_type))].sort(), [allOpps]);

  // Apply filters
  const opportunities = useMemo(() => {
    const minEdge = parseFloat(edgeInput);
    const minEdgeFrac = !isNaN(minEdge) && minEdge > 0 ? minEdge / 100 : 0;
    const searchLower = filterSearch.toLowerCase().trim();

    return allOpps.filter((o) => {
      if (filterStatus !== "all" && o.status !== filterStatus) return false;
      if (filterPlatform !== "all" && o.platform !== filterPlatform) return false;
      if (filterSport !== "all" && o.sport !== filterSport) return false;
      if (filterMarketType === "props" && !isPropType(o.market_type)) return false;
      if (filterMarketType === "main" && isPropType(o.market_type)) return false;
      if (filterMarketType !== "all" && filterMarketType !== "props" && filterMarketType !== "main" && o.market_type !== filterMarketType) return false;
      if (minEdgeFrac > 0 && o.edge < minEdgeFrac) return false;
      if (searchLower && !o.event.toLowerCase().includes(searchLower) && !o.side.toLowerCase().includes(searchLower)) return false;
      return true;
    });
  }, [allOpps, filterStatus, filterPlatform, filterSport, filterMarketType, filterSearch, edgeInput]);

  const activeFilterCount = [
    filterStatus !== "all",
    filterPlatform !== "all",
    filterSport !== "all",
    filterMarketType !== "all",
    filterSearch.trim().length > 0,
  ].filter(Boolean).length;

  const displayed = selected && opportunities.some((o) => oppKey(o) === oppKey(selected))
    ? selected
    : opportunities[0] ?? null;
  const displayedIsTaken = displayed ? isTaken(displayed) : false;

  const buyCount = allOpps.filter((o) => o.status === "BUY").length;
  const watchCount = allOpps.filter((o) => o.status === "WATCH").length;
  const platforms = availablePlatforms;
  const openPositions = positions.filter((p) => p.status === "open").length;

  // Quota from last response
  const quotaRemaining = data.quota_remaining;

  // True when backend has produced at least one snapshot
  const hasSnapshot = updatedAt != null;

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
            disabled={scanning}
            className="px-4 py-1 rounded-md border font-mono text-[10px] tracking-wider uppercase transition-all duration-150"
            style={{
              color: scanning ? "#374151" : "#2dd4bf",
              background: scanning ? "rgba(75,85,99,0.05)" : "rgba(45,212,191,0.06)",
              borderColor: scanning ? "rgba(75,85,99,0.15)" : "rgba(45,212,191,0.2)",
            }}
          >
            {scanning ? "Scanning..." : "Scan"}
          </button>
        </form>

        <div className="flex items-center gap-4 font-mono text-[9px]" style={{ color: "#374151" }}>
          <span>
            {activeFilterCount > 0
              ? `${opportunities.length}/${allOpps.length} shown`
              : `${allOpps.length} results`}{" "}
            ({buyCount} buy, {watchCount} watch)
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
          <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
          <button
            onClick={async () => {
              try {
                if (monitorRunning) await stopMonitoring();
                else await startMonitoring();
                monitor.reload();
              } catch { /* silent */ }
            }}
            className="flex items-center gap-1.5 transition-all"
            title={monitorRunning ? "Stop auto-update" : "Start auto-update"}
          >
            <span
              className="w-1.5 h-1.5 rounded-full transition-all"
              style={{
                background: monitorRunning ? "#4ade80" : "#374151",
                boxShadow: monitorRunning ? "0 0 4px #4ade80" : "none",
              }}
            />
            <span style={{ color: monitorRunning ? "#4ade80" : "#374151" }}>
              Auto
            </span>
          </button>
          <div className="h-3 w-px" style={{ background: "rgba(75,85,99,0.15)" }} />
          <div className="flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: (scanning || backendRefreshing) ? "#f59e0b" : updatedAt ? "#4ade80" : "#374151",
                boxShadow: (scanning || backendRefreshing) ? "0 0 4px #f59e0b" : updatedAt ? "0 0 4px #4ade80" : "none",
              }}
            />
            <span suppressHydrationWarning>
              {scanning ? "Updating..." : backendRefreshing ? "Updating..." : !mounted ? "" : updatedAt ? `${timeAgo(new Date(updatedAt * 1000))}` : "Waiting for data..."}
            </span>
          </div>
        </div>
      </div>

      {/* Filter bar */}
      <div
        className="flex items-center gap-3 px-4 py-2 rounded-lg border"
        style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.25)" }}
      >
        <span className="font-mono text-[8px] tracking-[0.15em] uppercase shrink-0" style={{ color: "#374151" }}>
          Filter
        </span>

        {/* Search */}
        <input
          type="text"
          placeholder="Player / team..."
          value={filterSearch}
          onChange={(e) => setFilterSearch(e.target.value)}
          className="w-32 px-2 py-1 rounded border font-mono text-[11px] focus:outline-none focus:border-[rgba(45,212,191,0.5)]"
          style={{ background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" }}
        />

        <div className="h-3.5 w-px shrink-0" style={{ background: "rgba(75,85,99,0.15)" }} />

        {/* Status */}
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value as "all" | "BUY" | "WATCH")}
          className="px-2 py-1 rounded border font-mono text-[11px] focus:outline-none"
          style={{ background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" }}
        >
          <option value="all">All Status</option>
          <option value="BUY">BUY only</option>
          <option value="WATCH">WATCH only</option>
        </select>

        {/* Platform */}
        {availablePlatforms.length > 1 && (
          <select
            value={filterPlatform}
            onChange={(e) => setFilterPlatform(e.target.value)}
            className="px-2 py-1 rounded border font-mono text-[11px] focus:outline-none"
            style={{ background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" }}
          >
            <option value="all">All Platforms</option>
            {availablePlatforms.map((p) => (
              <option key={p} value={p}>{p === "polymarket" ? "Polymarket" : p === "kalshi" ? "Kalshi" : p}</option>
            ))}
          </select>
        )}

        {/* Sport */}
        {availableSports.length > 1 && (
          <select
            value={filterSport}
            onChange={(e) => setFilterSport(e.target.value)}
            className="px-2 py-1 rounded border font-mono text-[11px] focus:outline-none"
            style={{ background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" }}
          >
            <option value="all">All Sports</option>
            {availableSports.map((s) => (
              <option key={s} value={s}>{sportLabel(s, sportsRegistry)}</option>
            ))}
          </select>
        )}

        {/* Market type */}
        {availableMarketTypes.length > 1 && (() => {
          const hasProps = availableMarketTypes.some(isPropType);
          const mainTypes = availableMarketTypes.filter((t) => !isPropType(t));
          const propTypes = availableMarketTypes.filter(isPropType);
          return (
            <select
              value={filterMarketType}
              onChange={(e) => setFilterMarketType(e.target.value)}
              className="px-2 py-1 rounded border font-mono text-[11px] focus:outline-none"
              style={{ background: "rgba(13,20,22,0.8)", borderColor: "rgba(19,78,74,0.3)", color: "#e2e8f0" }}
            >
              <option value="all">All Types</option>
              {hasProps && <option value="props">All Props</option>}
              {hasProps && <option value="main">Main Lines</option>}
              {mainTypes.length > 0 && <option disabled>───────</option>}
              {mainTypes.map((t) => (
                <option key={t} value={t}>{marketTypeLabel(t)}</option>
              ))}
              {propTypes.length > 0 && <option disabled>── Props ──</option>}
              {propTypes.map((t) => (
                <option key={t} value={t}>{marketTypeLabel(t)}</option>
              ))}
            </select>
          );
        })()}

        {/* Clear filters */}
        {activeFilterCount > 0 && (
          <button
            onClick={() => {
              setFilterStatus("all");
              setFilterPlatform("all");
              setFilterSport("all");
              setFilterMarketType("all");
              setFilterSearch("");
            }}
            title="Clear all filters"
            className="px-2 py-1 rounded border font-mono text-[10px] transition-colors"
            style={{ color: "#94a3b8", borderColor: "rgba(75,85,99,0.2)", background: "rgba(75,85,99,0.05)" }}
          >
            Clear ({activeFilterCount})
          </button>
        )}
      </div>

      {!hasSnapshot ? (
        /* No snapshot yet — cold start or backend initializing */
        <div
          className="rounded-lg border px-6 py-16 text-center"
          style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
        >
          <div className="flex items-center justify-center gap-2 mb-3">
            <span
              className="w-2 h-2 rounded-full animate-pulse"
              style={{ background: "#f59e0b", boxShadow: "0 0 6px #f59e0b" }}
            />
            <span className="font-mono text-[12px]" style={{ color: "#f59e0b" }}>
              Waiting for data...
            </span>
          </div>
          <p className="font-mono text-[10px]" style={{ color: "#374151" }}>
            The backend is building the first snapshot. This takes 10–30 seconds on cold start.
          </p>
          <p className="font-mono text-[10px] mt-1" style={{ color: "#374151" }}>
            Or click <strong style={{ color: "#2dd4bf" }}>Scan</strong> above to trigger a manual refresh.
          </p>
        </div>
      ) : (
        <>
          {/* Data source status */}
          <DataStatus />

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
                sportsRegistry={sportsRegistry}
                isRefreshing={scanning || backendRefreshing}
              />
            </div>
            <div className="space-y-3">
              <MarketDetailPanel
                opportunity={displayed}
                bankroll={bankroll}
                isTaken={displayedIsTaken}
                onTake={() => displayed && takePosition(displayed)}
                sportsRegistry={sportsRegistry}
              />
            </div>
          </div>

          {/* Tracked trades */}
          {positions.length > 0 && (
            <TrackedPositions
              positions={positions}
              onClose={closePosition}
              onRemove={removePosition}
              sportsRegistry={sportsRegistry}
            />
          )}
        </>
      )}
    </main>
  );
}
