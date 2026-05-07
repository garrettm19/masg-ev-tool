"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchMakerConfig,
  fetchMakerSummary,
  updateMakerConfig,
} from "@/lib/api";
import type { MakerConfig, MakerSummary } from "@/lib/types";
import { Badge } from "../ui/Badge";
import { Toggle } from "../ui/Toggle";
import { ConfirmDialog } from "../ui/ConfirmDialog";

// ---------------------------------------------------------------------------
// Layout primitives — match the visual rhythm of NotificationSettings (uppercase
// mono labels, var(--bg-surface) cards, accent/warn/info from CSS tokens).  No
// emojis, no danger styling: this control is read-only audit + a safe paper
// toggle, never live trading.
// ---------------------------------------------------------------------------

function Stat({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5" title={title}>
      <span
        className="font-mono uppercase tracking-[0.12em]"
        style={{ fontSize: "8px", color: "var(--fg-faint)" }}
      >
        {label}
      </span>
      <span
        className="font-mono font-medium"
        style={{
          fontSize: "12px",
          color: "var(--fg-primary)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function fmtPct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

interface Props {
  // Bumped by DashboardClient whenever a scan finishes — triggers a summary
  // refetch so the latest-run numbers reflect the freshest scan.
  scanRefreshKey?: number;
}

export function PaperMakerControls({ scanRefreshKey }: Props) {
  const [config, setConfig] = useState<MakerConfig | null>(null);
  const [summary, setSummary] = useState<MakerSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Initial + manual reload — pulls config and the latest-run summary.  We
  // request days=1 because the runtime maker store rolls the day file at UTC
  // midnight; latest_run=true narrows further to one scan's worth of data.
  const reload = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        fetchMakerConfig(),
        fetchMakerSummary({ days: 1, latest_run: true }),
      ]);
      setConfig(c);
      setSummary(s);
      setError(null);
    } catch {
      setError("Could not reach paper maker config.");
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // Re-fetch the latest-run summary every time DashboardClient signals a scan
  // finished.  Config doesn't change on scan, but refetching it too keeps the
  // safety-invariant readout honest if anything else in the system flipped it.
  useEffect(() => {
    if (scanRefreshKey == null) return;
    reload();
  }, [scanRefreshKey, reload]);

  const enabled = config?.enabled ?? false;

  const handleToggle = useCallback(
    (next: boolean) => {
      if (next === enabled) return;
      if (next) {
        // Show the safe-copy confirm before flipping ON.  Disabling is not
        // gated — it's strictly safer to turn off than to keep on.
        setConfirmOpen(true);
        return;
      }
      void doUpdate({ enabled: false });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enabled],
  );

  const doUpdate = useCallback(
    async (update: { enabled: boolean }) => {
      setPending(true);
      try {
        const next = await updateMakerConfig(update);
        setConfig(next);
        setError(null);
        // Refresh summary so the counts reflect the new state immediately
        // (e.g., disabling doesn't add records but the user expects a live view).
        try {
          const s = await fetchMakerSummary({ days: 1, latest_run: true });
          setSummary(s);
        } catch {
          /* summary refresh failure is non-fatal */
        }
      } catch {
        setError(
          update.enabled
            ? "Could not enable paper maker."
            : "Could not disable paper maker.",
        );
      } finally {
        setPending(false);
        setConfirmOpen(false);
      }
    },
    [],
  );

  const minEdge = config?.min_estimated_maker_edge ?? 0.05;
  const platforms = config?.platforms?.join(", ") ?? "kalshi";
  const marketTypes = config?.market_types?.join(", ") ?? "h2h";
  const total = summary?.total ?? 0;
  const eligible = summary?.eligible ?? 0;
  const rejected = summary?.rejected ?? 0;

  return (
    <>
      <div
        className="rounded-lg border"
        style={{
          background: "var(--bg-surface)",
          borderColor: "var(--border-default)",
          borderRadius: "var(--radius-lg)",
        }}
      >
        <div className="flex items-center justify-between gap-3 px-4 py-2.5">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="font-mono uppercase tracking-wider font-semibold"
              style={{ fontSize: "11px", color: "var(--fg-primary)" }}
            >
              Paper Maker
            </span>
            <Badge label="Paper Only" variant="warn" title="Records only — never places real orders" />
            <Badge
              label={enabled ? "On" : "Off"}
              variant={enabled ? "accent" : "platform"}
            />
          </div>
          <Toggle
            checked={enabled}
            onCheckedChange={handleToggle}
            disabled={pending || config == null}
            label={enabled ? "Disable Paper Maker" : "Enable Paper Maker"}
          />
        </div>

        <div
          className="px-4 py-2.5 border-t grid gap-3"
          style={{
            borderColor: "var(--border-subtle)",
            gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
          }}
        >
          <Stat
            label="Platforms"
            value={platforms}
            title="Locked server-side; UI cannot enable Polymarket maker."
          />
          <Stat
            label="Market Types"
            value={marketTypes}
            title="Locked server-side; H2H only in v1."
          />
          <Stat
            label="Min Maker Edge"
            value={fmtPct(minEdge, 1)}
            title="Eligible proposals must clear this estimated maker edge."
          />
          <Stat
            label="Latest Run · Total"
            value={String(total)}
            title="All proposals (eligible + rejected) from the most recent scan."
          />
          <Stat
            label="Latest Run · Eligible"
            value={String(eligible)}
            title="Proposals that passed every maker policy rule in the latest scan."
          />
          <Stat
            label="Latest Run · Rejected"
            value={String(rejected)}
            title="Proposals persisted for audit but rejected by the maker policy."
          />
        </div>

        {error && (
          <div
            className="px-4 py-2 border-t font-mono"
            style={{
              borderColor: "var(--border-subtle)",
              fontSize: "10px",
              color: "var(--warn-strong)",
            }}
          >
            {error}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Enable Paper Maker"
        description={
          <div className="space-y-2">
            <p>
              Paper maker only creates simulated proposal records. It does not
              place orders.
            </p>
            <p style={{ color: "var(--fg-muted)" }}>
              Scope is locked server-side: Kalshi only, h2h markets only, paper
              mode only. There is no order-placement code path in the
              application.
            </p>
            <p style={{ color: "var(--fg-muted)" }}>
              Each scan will append rejected and eligible audit records to a
              local JSONL file. Use the dashboard&rsquo;s detail panel to view a
              market&rsquo;s latest-run plan.
            </p>
          </div>
        }
        confirmLabel={pending ? "Enabling..." : "Enable Paper Maker"}
        cancelLabel="Cancel"
        confirmVariant="primary"
        onConfirm={() => {
          if (pending) return;
          void doUpdate({ enabled: true });
        }}
        onCancel={() => {
          if (pending) return;
          setConfirmOpen(false);
        }}
      />
    </>
  );
}
