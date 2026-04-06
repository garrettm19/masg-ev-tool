"use client";

import { Opportunity } from "@/lib/types";

interface Props {
  opportunities: Opportunity[];
  selectedId?: string;
  onSelect?: (opp: Opportunity) => void;
  bankroll?: number;
}

function fmtPct(n: number, dec = 1): string {
  return `${(n * 100).toFixed(dec)}%`;
}

function fmtOdds(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${months[d.getUTCMonth()]} ${d.getUTCDate()}, ${hh}:${mm}`;
}

function platformLabel(p: string): string {
  if (p === "polymarket") return "Polymarket";
  if (p === "kalshi") return "Kalshi";
  return p.charAt(0).toUpperCase() + p.slice(1);
}

function platformColor(p: string): string {
  if (p === "polymarket") return "#a78bfa";
  if (p === "kalshi") return "#38bdf8";
  return "#94a3b8";
}

function sportLabel(sport: string): string {
  if (sport.startsWith("tennis")) return "Tennis";
  if (sport.startsWith("mma")) return "MMA";
  if (sport.startsWith("cricket")) return "Cricket";
  if (sport.startsWith("rugby")) return "Rugby";
  if (sport.startsWith("americanfootball_ufl")) return "UFL";
  if (sport.startsWith("icehockey_ahl")) return "Hockey";
  return sport.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function edgeColor(edge: number): string {
  if (edge >= 0.10) return "#2dd4bf";
  if (edge >= 0.05) return "#67e8f9";
  if (edge >= 0.02) return "#a7f3d0";
  return "#94a3b8";
}

type Status = "BUY" | "WATCH" | "SKIP";

const STATUS_STYLE: Record<Status, { color: string; bg: string; border: string }> = {
  BUY:   { color: "#2dd4bf", bg: "rgba(45,212,191,0.08)",  border: "rgba(45,212,191,0.25)" },
  WATCH: { color: "#38bdf8", bg: "rgba(56,189,248,0.06)",  border: "rgba(56,189,248,0.2)"  },
  SKIP:  { color: "#4b5563", bg: "rgba(75,85,99,0.05)",    border: "rgba(75,85,99,0.15)"   },
};

const MARKET_TYPE_LABEL: Record<string, string> = {
  h2h: "H2H", handicap: "HCAP", totals: "TOT", first_set: "1ST", unknown: "?",
};

export function OpportunitiesTable({ opportunities, selectedId, onSelect, bankroll = 1000 }: Props) {
  const rows = opportunities.slice(0, 30);

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-2.5 border-b"
        style={{ borderColor: "rgba(19,78,74,0.25)" }}
      >
        <div className="flex items-center gap-3">
          <span
            className="font-mono text-[10px] tracking-[0.15em] uppercase font-medium"
            style={{ color: "#2dd4bf" }}
          >
            Opportunities
          </span>
          <span className="font-mono text-[9px]" style={{ color: "#374151" }}>
            {rows.length} matched, sorted by edge
          </span>
        </div>
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: rows.length > 0 ? "#2dd4bf" : "#374151", boxShadow: rows.length > 0 ? "0 0 6px #2dd4bf" : "none" }}
        />
      </div>

      {rows.length === 0 ? (
        <div className="px-4 py-16 text-center space-y-2">
          <p className="font-mono text-[12px]" style={{ color: "#374151" }}>
            No opportunities found
          </p>
          <p className="font-mono text-[10px]" style={{ color: "#1f3a3d" }}>
            Try lowering the minimum edge threshold or check back when more matches are scheduled
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(19,78,74,0.2)" }}>
                {[
                  { label: "Event",     align: "left"   },
                  { label: "Side",      align: "left"   },
                  { label: "Start",     align: "left"   },
                  { label: "Price",     align: "right"  },
                  { label: "FD Odds",   align: "right"  },
                  { label: "True Prob", align: "right"  },
                  { label: "Edge",      align: "right"  },
                  { label: "Kelly",     align: "right"  },
                  { label: "Bet Size",  align: "right"  },
                  { label: "Status",    align: "center" },
                  { label: "Trade",     align: "center" },
                ].map((col) => (
                  <th
                    key={col.label}
                    className={`px-3 py-2.5 font-mono text-[9px] tracking-[0.12em] uppercase whitespace-nowrap font-normal
                      ${col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"}`}
                    style={{ color: "#374151" }}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((opp, i) => {
                const ss = STATUS_STYLE[(opp.status as Status)] ?? STATUS_STYLE.SKIP;
                const isSelected = selectedId === opp.market_id;
                const pColor = platformColor(opp.platform);

                return (
                  <tr
                    key={`${opp.market_id}-${opp.side}`}
                    onClick={() => onSelect?.(opp)}
                    style={{
                      borderBottom: "1px solid rgba(19,78,74,0.08)",
                      background: isSelected
                        ? "rgba(45,212,191,0.06)"
                        : i % 2 === 0 ? "transparent" : "rgba(13,20,22,0.35)",
                    }}
                    className="hover:bg-[rgba(45,212,191,0.04)] transition-colors duration-100 cursor-pointer"
                  >
                    {/* Event */}
                    <td className="px-3 py-3" style={{ minWidth: 220 }}>
                      <p className="font-mono text-[11px] leading-snug" style={{ color: "#cbd5e1" }}>
                        {opp.event}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <span
                          className="font-mono text-[7px] tracking-wider px-1 py-px rounded uppercase shrink-0"
                          style={{ color: "#67e8f9", background: "rgba(103,232,249,0.08)" }}
                        >
                          {sportLabel(opp.sport)}
                        </span>
                        <span className="font-mono text-[9px]" style={{ color: "#374151" }}>
                          {opp.tournament}
                        </span>
                        <span
                          className="font-mono text-[7px] tracking-wider px-1 py-px rounded uppercase shrink-0"
                          style={{ color: pColor, background: `${pColor}14` }}
                        >
                          {platformLabel(opp.platform)}
                        </span>
                      </div>
                    </td>

                    {/* Side */}
                    <td className="px-3 py-3">
                      <span className="font-mono text-[11px] font-medium" style={{ color: "#e2e8f0" }}>
                        {opp.side.split(" ").pop()}
                      </span>
                      {opp.line != null && (
                        <span className="font-mono text-[9px] ml-1" style={{ color: "#6b7280" }}>
                          {opp.line > 0 ? `+${opp.line}` : opp.line}
                        </span>
                      )}
                    </td>

                    {/* Start */}
                    <td className="px-3 py-3 font-mono text-[10px] whitespace-nowrap" style={{ color: "#4b5563" }}>
                      {fmtTime(opp.start_time)}
                    </td>

                    {/* Price */}
                    <td className="px-3 py-3 text-right font-mono text-[11px]" style={{ color: "#94a3b8" }}>
                      {(opp.pm_price * 100).toFixed(1)}{"¢"}
                    </td>

                    {/* FD Odds */}
                    <td className="px-3 py-3 text-right font-mono text-[10px]" style={{ color: "#6b7280" }}>
                      {fmtOdds(opp.fd_odds)}
                    </td>

                    {/* True Prob */}
                    <td className="px-3 py-3 text-right font-mono text-[11px]" style={{ color: "#e2e8f0" }}>
                      {fmtPct(opp.p_true)}
                    </td>

                    {/* Edge */}
                    <td className="px-3 py-3 text-right">
                      <span className="font-mono text-[12px] font-semibold" style={{ color: edgeColor(opp.edge) }}>
                        +{fmtPct(opp.edge)}
                      </span>
                    </td>

                    {/* Kelly */}
                    <td className="px-3 py-3 text-right font-mono text-[10px]" style={{ color: "#38bdf8" }}>
                      {opp.recommended_kelly > 0 ? fmtPct(opp.recommended_kelly) : "--"}
                    </td>

                    {/* Bet Size */}
                    <td className="px-3 py-3 text-right font-mono text-[11px]" style={{ color: opp.recommended_kelly > 0 ? "#e2e8f0" : "#374151" }}>
                      {opp.recommended_kelly > 0
                        ? `$${Math.round(bankroll * opp.recommended_kelly).toLocaleString()}`
                        : "--"}
                    </td>

                    {/* Status */}
                    <td className="px-3 py-3 text-center">
                      <span
                        className="inline-block font-mono text-[9px] tracking-wider px-2.5 py-1 rounded-md border font-medium"
                        style={{ color: ss.color, background: ss.bg, borderColor: ss.border }}
                      >
                        {opp.status}
                      </span>
                    </td>

                    {/* Trade link */}
                    <td className="px-3 py-3 text-center">
                      {opp.event_url ? (
                        <a
                          href={opp.event_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 font-mono text-[9px] px-2.5 py-1 rounded-md border transition-all duration-150"
                          style={{
                            color: pColor,
                            background: `${pColor}08`,
                            borderColor: `${pColor}30`,
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = `${pColor}18`;
                            e.currentTarget.style.borderColor = `${pColor}50`;
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = `${pColor}08`;
                            e.currentTarget.style.borderColor = `${pColor}30`;
                          }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          View
                          <svg width="8" height="8" viewBox="0 0 10 10" fill="none" style={{ opacity: 0.7 }}>
                            <path d="M1 9L9 1M9 1H3M9 1V7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </a>
                      ) : (
                        <span className="font-mono text-[9px]" style={{ color: "#1f3a3d" }}>--</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
