"use client";

import { useState, useEffect, useCallback } from "react";
import { SportDataStatus, BookStatus } from "@/lib/types";
import { fetchDataStatus } from "@/lib/api";

function ageLabel(seconds: number | null): string {
  if (seconds == null) return "";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function BookCell({ book, name }: { book: BookStatus; name: string }) {
  if (!book.has_data) {
    return (
      <span className="font-mono text-[9px]" style={{ color: "#374151" }}>
        —
      </span>
    );
  }
  const age = ageLabel(book.cache_age_seconds);
  const fresh = book.cache_age_seconds != null && book.cache_age_seconds < 900;

  // Kalshi: show "raw / matched" when raw_count is available
  if (name === "Kalshi" && book.raw_count != null && book.raw_count > 0) {
    const matched = book.event_count;
    const rawColor = fresh ? "#4ade80" : "#f59e0b";
    const matchedColor = matched > 0 ? rawColor : "#6b7280";
    return (
      <span className="font-mono text-[9px]">
        <span style={{ color: rawColor }}>{book.raw_count}</span>
        <span style={{ color: "#374151" }}>{" / "}</span>
        <span style={{ color: matchedColor }}>{matched}</span>
        {age ? <span style={{ color: "#374151" }}>{` (${age})`}</span> : null}
      </span>
    );
  }

  return (
    <span className="font-mono text-[9px]" style={{ color: fresh ? "#4ade80" : "#f59e0b" }}>
      {book.event_count} {age ? `(${age})` : ""}
    </span>
  );
}

export function DataStatus() {
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<SportDataStatus[] | null>(null);

  const load = useCallback(async () => {
    try { setData(await fetchDataStatus()); } catch { /* silent */ }
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 15000); return () => clearInterval(iv); }, [load]);

  if (!data) return null;

  const totalSports = data.length;
  const withData = data.filter((d) => d.fanduel.has_data || d.polymarket.has_data || d.kalshi.has_data).length;

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.25)" }}
    >
      <div
        className="flex items-center justify-between px-4 py-2 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tracking-[0.15em] uppercase font-medium" style={{ color: "#67e8f9" }}>
            Data Sources
          </span>
          <span className="font-mono text-[9px]" style={{ color: "#374151" }}>
            {withData}/{totalSports} sports with data
          </span>
        </div>
        <span className="font-mono text-[10px]" style={{ color: "#374151" }}>
          {expanded ? "\u25B2" : "\u25BC"}
        </span>
      </div>

      {expanded && (
        <div className="px-4 pb-3" style={{ borderTop: "1px solid rgba(19,78,74,0.15)" }}>
          <table className="w-full mt-2">
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(19,78,74,0.15)" }}>
                <th className="text-left font-mono text-[8px] tracking-[0.12em] uppercase py-1.5 pr-4" style={{ color: "#374151" }}>Sport</th>
                <th className="text-center font-mono text-[8px] tracking-[0.12em] uppercase py-1.5 px-3" style={{ color: "#374151" }}>FanDuel</th>
                <th className="text-center font-mono text-[8px] tracking-[0.12em] uppercase py-1.5 px-3" style={{ color: "#a78bfa" }}>Polymarket</th>
                <th className="text-center font-mono text-[8px] tracking-[0.12em] uppercase py-1.5 px-3" style={{ color: "#38bdf8" }}>Kalshi</th>
              </tr>
            </thead>
            <tbody>
              {data.map((sport) => (
                <tr key={sport.key} style={{ borderBottom: "1px solid rgba(19,78,74,0.06)" }}>
                  <td className="py-1.5 pr-4">
                    <span className="font-mono text-[10px]" style={{ color: "#e2e8f0" }}>
                      {sport.label}
                    </span>
                  </td>
                  <td className="py-1.5 px-3 text-center">
                    <BookCell book={sport.fanduel} name="FanDuel" />
                  </td>
                  <td className="py-1.5 px-3 text-center">
                    <BookCell book={sport.polymarket} name="Polymarket" />
                  </td>
                  <td className="py-1.5 px-3 text-center">
                    <BookCell book={sport.kalshi} name="Kalshi" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="font-mono text-[8px] mt-2" style={{ color: "#374151" }}>
            Green = cached &lt; 15m. Yellow = stale. Kalshi = raw / matched. — = no data.
          </p>
        </div>
      )}
    </div>
  );
}
