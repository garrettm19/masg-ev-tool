"use client";

import { useEffect, useState } from "react";
import { Opportunity } from "@/lib/types";
import { fetchPriceHistory } from "@/lib/api";

interface Props {
  opportunity: Opportunity | null;
}

interface Point {
  t: number;
  p: number;
}

function fmtDate(ts: number): string {
  const d = new Date(ts * 1000);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${months[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function fmtPrice(p: number): string {
  return `${(p * 100).toFixed(1)}c`;
}

function platformLabel(p: string): string {
  if (p === "polymarket") return "Polymarket";
  if (p === "kalshi") return "Kalshi";
  return p;
}

const W = 700;
const H = 180;
const PL = 48;
const PR = 12;
const PT = 16;
const PB = 28;
const CW = W - PL - PR;
const CH = H - PT - PB;

export function PriceChart({ opportunity }: Props) {
  const [points, setPoints] = useState<Point[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!opportunity) {
      setPoints([]);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(false);

    fetchPriceHistory(opportunity.platform, opportunity.market_id)
      .then((data) => {
        if (!cancelled) setPoints(data.points);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [opportunity?.platform, opportunity?.market_id]);

  // Empty state
  if (!opportunity) {
    return (
      <div
        className="rounded-lg border"
        style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
      >
        <div className="flex items-center px-4 py-2.5 border-b" style={{ borderColor: "rgba(19,78,74,0.25)" }}>
          <span className="font-mono text-[10px] tracking-[0.12em] uppercase font-medium" style={{ color: "#2dd4bf", opacity: 0.4 }}>
            Price History
          </span>
        </div>
        <div className="flex items-center justify-center py-12">
          <p className="font-mono text-[10px]" style={{ color: "#374151" }}>
            Select an opportunity to view price history
          </p>
        </div>
      </div>
    );
  }

  const hasData = points.length >= 2;

  // Compute chart geometry
  let yMin = 0, yMax = 1, linePath = "", areaPath = "";
  let gridYs: number[] = [];
  let xLabels: { x: number; label: string }[] = [];

  if (hasData) {
    const prices = points.map((p) => p.p);
    const rawMin = Math.min(...prices);
    const rawMax = Math.max(...prices);
    const pad = Math.max((rawMax - rawMin) * 0.15, 0.02);
    yMin = Math.max(0, rawMin - pad);
    yMax = Math.min(1, rawMax + pad);

    const cx = (i: number) => PL + (i / (points.length - 1)) * CW;
    const cy = (v: number) => PT + (1 - (v - yMin) / (yMax - yMin)) * CH;

    linePath = points
      .map((p, i) => `${i === 0 ? "M" : "L"}${cx(i).toFixed(1)},${cy(p.p).toFixed(1)}`)
      .join(" ");

    areaPath = linePath +
      ` L${cx(points.length - 1).toFixed(1)},${(PT + CH).toFixed(1)}` +
      ` L${PL},${(PT + CH).toFixed(1)} Z`;

    // Y grid: 4-5 lines
    const yStep = (yMax - yMin) / 4;
    gridYs = Array.from({ length: 5 }, (_, i) => yMin + i * yStep);

    // X labels: 5-6 evenly spaced
    const step = Math.max(1, Math.floor(points.length / 5));
    xLabels = points
      .filter((_, i) => i % step === 0 || i === points.length - 1)
      .map((p, _, arr) => ({
        x: PL + (points.indexOf(p) / (points.length - 1)) * CW,
        label: arr.length <= 6 ? fmtDate(p.t) : fmtTime(p.t),
      }));
  }

  const lastPrice = hasData ? points[points.length - 1].p : null;
  const firstPrice = hasData ? points[0].p : null;
  const priceChange = lastPrice != null && firstPrice != null ? lastPrice - firstPrice : 0;
  const isUp = priceChange >= 0;
  const lineColor = isUp ? "#2dd4bf" : "#f87171";

  return (
    <div
      className="rounded-lg border"
      style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{ borderColor: "rgba(19,78,74,0.25)" }}>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] tracking-[0.12em] uppercase font-medium" style={{ color: "#2dd4bf", opacity: 0.7 }}>
            Price History
          </span>
          <span className="font-mono text-[9px]" style={{ color: "#374151" }}>
            {opportunity.side} &middot; {platformLabel(opportunity.platform)}
          </span>
        </div>
        {hasData && lastPrice != null && (
          <div className="flex items-center gap-3 font-mono text-[10px]">
            <span style={{ color: "#94a3b8" }}>{fmtPrice(lastPrice)}</span>
            <span style={{ color: lineColor, fontWeight: 600 }}>
              {isUp ? "+" : ""}{(priceChange * 100).toFixed(1)}c
            </span>
          </div>
        )}
      </div>

      {/* Chart body */}
      <div className="px-4 pt-3 pb-2">
        {loading ? (
          <div className="flex items-center justify-center" style={{ height: H }}>
            <span className="font-mono text-[10px] animate-pulse" style={{ color: "#374151" }}>Loading...</span>
          </div>
        ) : error || !hasData ? (
          <div className="flex items-center justify-center" style={{ height: H }}>
            <p className="font-mono text-[10px]" style={{ color: "#374151" }}>
              {error ? "Failed to load price data" : "No price history available yet"}
            </p>
          </div>
        ) : (
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }} preserveAspectRatio="none">
            <defs>
              <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity="0.12" />
                <stop offset="100%" stopColor={lineColor} stopOpacity="0.01" />
              </linearGradient>
            </defs>

            {/* Grid lines */}
            {gridYs.map((v, i) => {
              const y = PT + (1 - (v - yMin) / (yMax - yMin)) * CH;
              return (
                <g key={i}>
                  <line
                    x1={PL} y1={y} x2={W - PR} y2={y}
                    stroke="#1a2e30" strokeWidth="1"
                  />
                  <text
                    x={PL - 6} y={y + 3.5}
                    textAnchor="end" fontSize="8"
                    fill="#374151" fontFamily="ui-monospace,monospace"
                  >
                    {(v * 100).toFixed(0)}c
                  </text>
                </g>
              );
            })}

            {/* Area fill */}
            <path d={areaPath} fill="url(#chartGrad)" />

            {/* Line */}
            <path
              d={linePath}
              fill="none"
              stroke={lineColor}
              strokeWidth="1.5"
              style={{ filter: `drop-shadow(0 0 2px ${lineColor})` }}
            />

            {/* End dot */}
            <circle
              cx={PL + CW}
              cy={PT + (1 - (points[points.length - 1].p - yMin) / (yMax - yMin)) * CH}
              r="3"
              fill={lineColor}
              style={{ filter: `drop-shadow(0 0 4px ${lineColor})` }}
            />

            {/* X labels */}
            {xLabels.map((l, i) => (
              <text
                key={i}
                x={l.x} y={H - 4}
                textAnchor="middle" fontSize="8"
                fill="#374151" fontFamily="ui-monospace,monospace"
              >
                {l.label}
              </text>
            ))}
          </svg>
        )}
      </div>
    </div>
  );
}
