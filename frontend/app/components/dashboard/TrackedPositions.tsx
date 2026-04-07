"use client";

import { TrackedPosition } from "@/lib/types";

interface Props {
  positions: TrackedPosition[];
  onClose: (id: string) => void;
  onRemove: (id: string) => void;
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

export function TrackedPositions({ positions, onClose, onRemove }: Props) {
  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status === "closed");

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
    >
      <div
        className="flex items-center justify-between px-4 py-2.5 border-b"
        style={{ borderColor: "rgba(19,78,74,0.25)" }}
      >
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] tracking-[0.15em] uppercase font-medium" style={{ color: "#f59e0b" }}>
            Tracked Positions
          </span>
          <span className="font-mono text-[9px]" style={{ color: "#374151" }}>
            {open.length} open{closed.length > 0 ? `, ${closed.length} closed` : ""}
          </span>
        </div>
      </div>

      {positions.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <p className="font-mono text-[10px]" style={{ color: "#374151" }}>
            No positions tracked yet. Click "Mark Taken" on an opportunity to track it.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(19,78,74,0.15)" }}>
                {["Event", "Side", "Entry", "Edge", "Platform", "Taken", ""].map((label) => (
                  <th
                    key={label || "actions"}
                    className="px-3 py-2 font-mono text-[8px] tracking-[0.12em] uppercase whitespace-nowrap font-normal text-left"
                    style={{ color: "#374151" }}
                  >
                    {label}
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
                      opacity: isOpen ? 1 : 0.5,
                    }}
                  >
                    <td className="px-3 py-2">
                      <p className="font-mono text-[10px]" style={{ color: "#cbd5e1" }}>
                        {pos.event}
                      </p>
                    </td>
                    <td className="px-3 py-2 font-mono text-[10px] font-medium" style={{ color: "#e2e8f0" }}>
                      {pos.side.split(" ").pop()}
                      {pos.line != null && (
                        <span className="ml-1" style={{ color: "#6b7280" }}>
                          {pos.line > 0 ? `+${pos.line}` : pos.line}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-[10px]" style={{ color: "#94a3b8" }}>
                      {(pos.entry_price * 100).toFixed(1)}{"c"}
                    </td>
                    <td className="px-3 py-2 font-mono text-[10px]" style={{ color: "#2dd4bf" }}>
                      +{(pos.entry_edge * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 font-mono text-[8px] uppercase" style={{ color: "#6b7280" }}>
                      {platformShort(pos.platform)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[9px] whitespace-nowrap" style={{ color: "#374151" }}>
                      {fmtTime(pos.taken_at)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex items-center gap-1.5 justify-end">
                        {isOpen ? (
                          <button
                            onClick={() => onClose(pos.id)}
                            className="font-mono text-[8px] tracking-wider uppercase px-2 py-0.5 rounded-md border transition-all"
                            style={{ color: "#f59e0b", borderColor: "rgba(245,158,11,0.25)", background: "rgba(245,158,11,0.06)" }}
                          >
                            Close
                          </button>
                        ) : (
                          <span className="font-mono text-[8px] tracking-wider uppercase px-2 py-0.5 rounded-md" style={{ color: "#374151", background: "rgba(75,85,99,0.06)" }}>
                            Closed
                          </span>
                        )}
                        <button
                          onClick={() => onRemove(pos.id)}
                          className="font-mono text-[8px] px-1.5 py-0.5 rounded-md transition-all"
                          style={{ color: "#374151" }}
                          onMouseEnter={(e) => { e.currentTarget.style.color = "#f87171"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.color = "#374151"; }}
                        >
                          ×
                        </button>
                      </div>
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
