"use client";

import { useEffect, useState } from "react";
import { Opportunity } from "@/lib/types";
import { SportRegistryEntry } from "@/lib/sport-labels";
import { OpportunityRow } from "./OpportunityRow";

interface Props {
  opportunities: Opportunity[];
  selectedId?: string;
  onSelect?: (opp: Opportunity) => void;
  bankroll?: number;
  isTaken?: (opp: Opportunity) => boolean;
  sportsRegistry?: Record<string, SportRegistryEntry>;
  isRefreshing?: boolean;
}

interface Column {
  label: string;
  align: "left" | "right" | "center";
}

const COLUMNS: Column[] = [
  { label: "Event",         align: "left"   },
  { label: "Type",          align: "left"   },
  { label: "Detail",        align: "left"   },
  { label: "Side",          align: "left"   },
  { label: "Start (local)", align: "left"   },
  { label: "Price",         align: "right"  },
  { label: "Age",           align: "center" },
  { label: "FD Odds",       align: "right"  },
  { label: "True Prob",     align: "right"  },
  { label: "Edge",          align: "right"  },
  { label: "Kelly",         align: "right"  },
  { label: "Bet Size",      align: "right"  },
  { label: "Status",        align: "center" },
  { label: "Trade",         align: "center" },
];

export function OpportunitiesTable({
  opportunities,
  selectedId,
  onSelect,
  bankroll = 1000,
  isTaken,
  sportsRegistry,
  isRefreshing = false,
}: Props) {
  const rows = opportunities.slice(0, 30);

  // Stable across SSR/client: starts at 0 (renders "?"), hydrates on mount.
  // Single ticker for the whole table — children read via prop, no re-bind.
  const [nowSec, setNowSec] = useState(0);
  useEffect(() => {
    setNowSec(Date.now() / 1000);
    const iv = setInterval(() => setNowSec(Date.now() / 1000), 10_000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{
        background: "var(--bg-surface)",
        borderColor: "var(--border-default)",
        borderRadius: "var(--radius-lg)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-2.5 border-b"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <div className="flex items-center gap-3">
          <span
            className="font-mono uppercase tracking-[0.15em] font-medium"
            style={{ fontSize: "10px", color: "var(--accent)" }}
          >
            Opportunities
          </span>
          <span className="font-mono" style={{ fontSize: "10px", color: "var(--fg-ghost)" }}>
            {rows.length} matched, sorted by edge
          </span>
        </div>
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{
            background: rows.length > 0 ? "var(--accent)" : "var(--fg-ghost)",
            boxShadow: rows.length > 0 ? "0 0 6px var(--accent)" : "none",
          }}
          aria-hidden="true"
        />
      </div>

      {rows.length === 0 ? (
        <div className="px-4 py-16 text-center space-y-2">
          <p className="font-mono" style={{ fontSize: "12px", color: "var(--fg-ghost)" }}>
            No opportunities found
          </p>
          <p className="font-mono" style={{ fontSize: "11px", color: "var(--fg-disabled)" }}>
            Try lowering the minimum edge threshold or check back when more matches are scheduled
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                {COLUMNS.map((col) => (
                  <th
                    key={col.label}
                    scope="col"
                    className={
                      "px-3 py-2.5 font-mono uppercase whitespace-nowrap font-normal " +
                      (col.align === "right"
                        ? "text-right"
                        : col.align === "center"
                          ? "text-center"
                          : "text-left")
                    }
                    style={{
                      fontSize: "10px",
                      letterSpacing: "0.12em",
                      color: "var(--fg-ghost)",
                    }}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((opp, i) => (
                <OpportunityRow
                  key={`${opp.market_id}-${opp.side}`}
                  opp={opp}
                  index={i}
                  isSelected={selectedId === opp.market_id}
                  isTaken={isTaken?.(opp) ?? false}
                  bankroll={bankroll}
                  sportsRegistry={sportsRegistry}
                  nowSec={nowSec}
                  isRefreshing={isRefreshing}
                  onSelect={(o) => onSelect?.(o)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
