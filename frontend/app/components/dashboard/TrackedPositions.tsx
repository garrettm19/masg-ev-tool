"use client";

import { useState } from "react";
import { TrackedPosition } from "@/lib/types";
import { sportLabel, SportRegistryEntry } from "@/lib/sport-labels";

interface Props {
  positions: TrackedPosition[];
  onClose: (id: string, force?: boolean) => Promise<{ ok: boolean }>;
  onRemove: (id: string) => void;
  sportsRegistry?: Record<string, SportRegistryEntry>;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "--";
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${months[d.getMonth()]} ${d.getDate()}, ${hh}:${mm}`;
}

function platformShort(p: string): string {
  if (p === "polymarket") return "PM";
  if (p === "kalshi") return "KAL";
  return p.slice(0, 3).toUpperCase();
}

function fmtProb(n: number | null | undefined): string {
  if (n == null) return "--";
  return `${(n * 100).toFixed(1)}%`;
}

function fmtEv(n: number | null | undefined): string {
  if (n == null) return "--";
  const pct = n * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function evColor(n: number | null | undefined): string {
  if (n == null) return "#374151";
  return n >= 0 ? "#2dd4bf" : "#f87171";
}

// ---------------------------------------------------------------------------
// Summary Cards
// ---------------------------------------------------------------------------

function SummaryCards({ positions }: { positions: TrackedPosition[] }) {
  const closed = positions.filter((p) => p.status === "closed");
  const withEv = closed.filter((p) => p.entry_ev != null);
  const withClv = closed.filter((p) => p.clv_prob != null);

  const avgEntryEv =
    withEv.length > 0
      ? withEv.reduce((sum, p) => sum + p.entry_ev!, 0) / withEv.length
      : null;

  const avgClv =
    withClv.length > 0
      ? withClv.reduce((sum, p) => sum + p.clv_prob!, 0) / withClv.length
      : null;

  const clvWinRate =
    withClv.length > 0
      ? withClv.filter((p) => p.clv_prob! > 0).length / withClv.length
      : null;

  // Edge Held = avg CLV / avg Entry EV — what fraction of predicted edge survived
  const edgeHeld =
    avgEntryEv != null && avgEntryEv > 0 && avgClv != null
      ? avgClv / avgEntryEv
      : null;

  const cardStyle = {
    background: "rgba(13,20,22,0.6)",
    border: "1px solid rgba(19,78,74,0.2)",
    borderRadius: "8px",
    padding: "10px 14px",
  };
  const labelStyle = {
    color: "#374151", fontSize: "8px", letterSpacing: "0.12em",
    textTransform: "uppercase" as const, fontFamily: "monospace",
  };
  const bigStyle = (color: string) => ({
    color, fontSize: "16px", fontWeight: 600, fontFamily: "monospace",
  });
  const subStyle = { color: "#4b5563", fontSize: "9px", fontFamily: "monospace" };

  return (
    <div className="grid grid-cols-5 gap-2 px-4 pt-3">
      <div style={cardStyle}>
        <div style={labelStyle}>Trades</div>
        <div style={bigStyle("#e2e8f0")}>{positions.length}</div>
        <div style={subStyle}>{closed.length} closed</div>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Avg Entry EV</div>
        {avgEntryEv != null ? (
          <>
            <div style={bigStyle(evColor(avgEntryEv))}>{fmtEv(avgEntryEv)}</div>
            <div style={subStyle}>model edge</div>
          </>
        ) : (
          <div style={bigStyle("#374151")}>--</div>
        )}
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Avg CLV</div>
        {avgClv != null ? (
          <>
            <div style={bigStyle(evColor(avgClv))}>{fmtEv(avgClv)}</div>
            <div style={subStyle}>vs FD close</div>
          </>
        ) : (
          <div style={bigStyle("#374151")}>--</div>
        )}
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>CLV Win Rate</div>
        {clvWinRate != null ? (
          <>
            <div style={bigStyle(clvWinRate >= 0.5 ? "#2dd4bf" : "#f87171")}>
              {(clvWinRate * 100).toFixed(0)}%
            </div>
            <div style={subStyle}>
              {withClv.filter((p) => p.clv_prob! > 0).length}/{withClv.length} positive
            </div>
          </>
        ) : (
          <div style={bigStyle("#374151")}>--</div>
        )}
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Edge Held</div>
        {edgeHeld != null ? (
          <>
            <div style={bigStyle(edgeHeld >= 0.5 ? "#2dd4bf" : edgeHeld >= 0 ? "#fbbf24" : "#f87171")}>
              {(edgeHeld * 100).toFixed(0)}%
            </div>
            <div style={subStyle}>of entry EV</div>
          </>
        ) : (
          <div style={bigStyle("#374151")}>--</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

const COL_HEADERS = [
  { label: "Event",     align: "left"   },
  { label: "Side",      align: "left"   },
  { label: "Sport",     align: "left"   },
  { label: "Entry",     align: "right"  },
  { label: "FD Entry",  align: "right"  },
  { label: "FD Close",  align: "right"  },
  { label: "Entry EV",  align: "right"  },
  { label: "CLV",       align: "right"  },
  { label: "Status",    align: "center" },
  { label: "Taken",     align: "left"   },
  { label: "",          align: "right"  },
];

export function TrackedPositions({ positions, onClose, onRemove, sportsRegistry }: Props) {
  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status === "closed");
  const [closingId, setClosingId] = useState<string | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);

  async function handleClose(id: string, force?: boolean) {
    setClosingId(id);
    setFailedId(null);
    const { ok } = await onClose(id, force);
    setClosingId(null);
    if (!ok) setFailedId(id);
  }

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
          <span className="font-mono text-[10px] tracking-[0.15em] uppercase font-medium" style={{ color: "#f59e0b" }}>
            Tracked Trades
          </span>
          <span className="font-mono text-[9px]" style={{ color: "#374151" }}>
            {open.length} open{closed.length > 0 ? `, ${closed.length} closed` : ""}
          </span>
        </div>
      </div>

      {positions.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <p className="font-mono text-[10px]" style={{ color: "#374151" }}>
            No trades tracked yet. Click &ldquo;Mark Taken&rdquo; on an opportunity to track it.
          </p>
        </div>
      ) : (
        <>
          <SummaryCards positions={positions} />

          <div className="overflow-x-auto px-4 pb-3 pt-2">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(19,78,74,0.15)" }}>
                  {COL_HEADERS.map((col) => (
                    <th
                      key={col.label || "actions"}
                      className={`px-3 py-2 font-mono text-[8px] tracking-[0.12em] uppercase whitespace-nowrap font-normal
                        ${col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"}`}
                      style={{ color: "#374151" }}
                    >
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const isOpen = pos.status === "open";
                  return (
                    <tr
                      key={pos.id}
                      style={{
                        borderBottom: "1px solid rgba(19,78,74,0.06)",
                        opacity: isOpen ? 1 : 0.6,
                      }}
                    >
                      {/* Event */}
                      <td className="px-3 py-2" style={{ maxWidth: 220 }}>
                        <p className="font-mono text-[10px] truncate" style={{ color: "#cbd5e1" }}>
                          {pos.event}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="font-mono text-[7px] uppercase" style={{ color: "#6b7280" }}>
                            {platformShort(pos.platform)}
                          </span>
                          {pos.start_time && (
                            <span className="font-mono text-[7px]" style={{ color: "#4b5563" }}>
                              {fmtTime(pos.start_time)}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Side */}
                      <td className="px-3 py-2 font-mono text-[10px] font-medium" style={{ color: "#e2e8f0" }}>
                        {pos.side.split(" ").pop()}
                        {pos.line != null && (
                          <span className="ml-1" style={{ color: "#6b7280" }}>
                            {pos.line > 0 ? `+${pos.line}` : pos.line}
                          </span>
                        )}
                      </td>

                      {/* Sport */}
                      <td className="px-3 py-2">
                        <span
                          className="font-mono text-[7px] tracking-wider px-1 py-px rounded uppercase"
                          style={{ color: "#67e8f9", background: "rgba(103,232,249,0.08)" }}
                        >
                          {sportLabel(pos.sport, sportsRegistry)}
                        </span>
                      </td>

                      {/* Entry Price */}
                      <td className="px-3 py-2 text-right font-mono text-[10px]" style={{ color: "#94a3b8" }}>
                        {(pos.entry_price * 100).toFixed(1)}{"c"}
                      </td>

                      {/* FD Entry */}
                      <td className="px-3 py-2 text-right font-mono text-[10px]" style={{ color: "#94a3b8" }}>
                        {fmtProb(pos.p_true)}
                      </td>

                      {/* FD Close */}
                      <td className="px-3 py-2 text-right font-mono text-[10px]" style={{ color: "#94a3b8" }}>
                        {fmtProb(pos.fd_close_prob)}
                      </td>

                      {/* Entry EV */}
                      <td className="px-3 py-2 text-right font-mono text-[10px] font-medium" style={{ color: evColor(pos.entry_ev) }}>
                        {fmtEv(pos.entry_ev)}
                      </td>

                      {/* CLV */}
                      <td className="px-3 py-2 text-right font-mono text-[10px] font-medium" style={{ color: evColor(pos.clv_prob) }}>
                        {fmtEv(pos.clv_prob)}
                      </td>

                      {/* Status */}
                      <td className="px-3 py-2 text-center">
                        {isOpen ? (
                          <span
                            className="inline-block font-mono text-[8px] tracking-wider px-2 py-0.5 rounded-md border"
                            style={{ color: "#f59e0b", borderColor: "rgba(245,158,11,0.25)", background: "rgba(245,158,11,0.06)" }}
                          >
                            Open
                          </span>
                        ) : (
                          <span
                            className="inline-block font-mono text-[8px] tracking-wider px-2 py-0.5 rounded-md"
                            style={{ color: "#374151", background: "rgba(75,85,99,0.06)" }}
                          >
                            Closed
                          </span>
                        )}
                      </td>

                      {/* Taken */}
                      <td className="px-3 py-2 font-mono text-[9px] whitespace-nowrap" style={{ color: "#374151" }}>
                        {fmtTime(pos.taken_at)}
                      </td>

                      {/* Actions */}
                      <td className="px-3 py-2 text-right">
                        <div className="flex items-center gap-1.5 justify-end">
                          {isOpen && closingId === pos.id ? (
                            <span className="font-mono text-[8px] tracking-wider uppercase px-2 py-0.5" style={{ color: "#6b7280" }}>
                              ...
                            </span>
                          ) : isOpen && failedId === pos.id ? (
                            <>
                              <button
                                onClick={() => handleClose(pos.id)}
                                className="font-mono text-[8px] tracking-wider uppercase px-2 py-0.5 rounded-md border transition-all"
                                style={{ color: "#f87171", borderColor: "rgba(248,113,113,0.25)", background: "rgba(248,113,113,0.06)" }}
                              >
                                Retry
                              </button>
                              <button
                                onClick={() => handleClose(pos.id, true)}
                                className="font-mono text-[8px] tracking-wider uppercase px-1.5 py-0.5 rounded-md transition-all"
                                style={{ color: "#6b7280" }}
                                title="Close without CLV"
                              >
                                Skip
                              </button>
                            </>
                          ) : isOpen ? (
                            <button
                              onClick={() => handleClose(pos.id)}
                              className="font-mono text-[8px] tracking-wider uppercase px-2 py-0.5 rounded-md border transition-all"
                              style={{ color: "#f59e0b", borderColor: "rgba(245,158,11,0.25)", background: "rgba(245,158,11,0.06)" }}
                            >
                              Close
                            </button>
                          ) : null}
                          <button
                            onClick={() => onRemove(pos.id)}
                            className="font-mono text-[8px] px-1.5 py-0.5 rounded-md transition-all"
                            style={{ color: "#374151" }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = "#f87171"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = "#374151"; }}
                          >
                            x
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
