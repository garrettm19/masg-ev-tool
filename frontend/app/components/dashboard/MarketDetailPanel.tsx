"use client";

import { Opportunity } from "@/lib/types";

interface Props {
  opportunity?: Opportunity | null;
  bankroll?: number;
}

function Row({ label, value, valueColor = "#94a3b8" }: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="font-mono text-[10px]" style={{ color: "#4b5563" }}>{label}</span>
      <span className="font-mono text-[11px] font-medium" style={{ color: valueColor }}>{value}</span>
    </div>
  );
}

function Section({ children }: { children: string }) {
  return (
    <p className="font-mono text-[9px] tracking-[0.12em] uppercase pt-4 pb-1.5 font-medium" style={{ color: "#2dd4bf", opacity: 0.6 }}>
      {children}
    </p>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="font-mono text-[8px] tracking-wider px-1.5 py-0.5 rounded-md border uppercase"
      style={{ color, background: `${color}10`, borderColor: `${color}30` }}
    >
      {label}
    </span>
  );
}

function edgeColor(edge: number): string {
  if (edge >= 0.10) return "#2dd4bf";
  if (edge >= 0.05) return "#67e8f9";
  if (edge >= 0.02) return "#a7f3d0";
  return "#94a3b8";
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
  return `${months[d.getUTCMonth()]} ${d.getUTCDate()}, ${hh}:${mm} UTC`;
}

function sportLabel(sport: string): string {
  if (sport.startsWith("tennis")) return "Tennis";
  if (sport.startsWith("mma")) return "MMA";
  if (sport.startsWith("cricket")) return "Cricket";
  if (sport.startsWith("rugby")) return "Rugby";
  if (sport.startsWith("americanfootball_ufl")) return "UFL";
  if (sport.startsWith("icehockey_ahl")) return "Hockey";
  return sport;
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

const MARKET_TYPE_LABEL: Record<string, string> = {
  h2h: "Moneyline H2H", handicap: "Handicap", totals: "Totals", first_set: "First Set", unknown: "Unknown",
};

const FD_CONF_COLOR: Record<string, string> = { High: "#2dd4bf", Medium: "#f59e0b", Low: "#4b5563" };
const LW_COLOR: Record<string, string> = { Tight: "#2dd4bf", Moderate: "#f59e0b", Wide: "#4b5563" };
const STATUS_COLOR: Record<string, string> = { BUY: "#2dd4bf", WATCH: "#38bdf8", SKIP: "#4b5563" };

export function MarketDetailPanel({ opportunity: opp, bankroll = 1000 }: Props) {
  if (!opp) {
    return (
      <div
        className="rounded-lg border flex flex-col"
        style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
      >
        <div className="px-4 py-2.5 border-b" style={{ borderColor: "rgba(19,78,74,0.25)" }}>
          <span className="font-mono text-[10px] tracking-[0.12em] uppercase font-medium" style={{ color: "#2dd4bf", opacity: 0.5 }}>
            Details
          </span>
        </div>
        <div className="flex flex-col items-center justify-center flex-1 py-14 gap-2">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" style={{ opacity: 0.15 }}>
            <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" stroke="#2dd4bf" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <p className="font-mono text-[10px]" style={{ color: "#374151" }}>
            Select an opportunity to view details
          </p>
        </div>
      </div>
    );
  }

  const typeLabel = MARKET_TYPE_LABEL[opp.market_type] ?? opp.market_type;
  const fdConfColor = FD_CONF_COLOR[opp.fanduel_confidence_label] ?? "#4b5563";
  const lwColor = LW_COLOR[opp.fanduel_line_width_label] ?? "#4b5563";
  const statusColor = STATUS_COLOR[opp.status] ?? "#4b5563";
  const pColor = platformColor(opp.platform);

  return (
    <div
      className="rounded-lg border flex flex-col"
      style={{ background: "#0c1315", borderColor: "rgba(19,78,74,0.35)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{ borderColor: "rgba(19,78,74,0.25)" }}>
        <span className="font-mono text-[10px] tracking-[0.12em] uppercase font-medium" style={{ color: "#2dd4bf", opacity: 0.7 }}>
          Details
        </span>
        <div className="flex items-center gap-1.5">
          <Badge label={platformLabel(opp.platform)} color={pColor} />
          <Badge label={opp.status} color={statusColor} />
        </div>
      </div>

      <div className="px-4 pb-4 flex-1 overflow-y-auto">
        {/* Event header */}
        <div className="py-3 border-b" style={{ borderColor: "rgba(19,78,74,0.12)" }}>
          <p className="font-mono text-[12px] leading-snug font-medium" style={{ color: "#e2e8f0" }}>
            {opp.event}
          </p>
          <p className="font-mono text-[9px] mt-1.5" style={{ color: "#4b5563" }}>
            {opp.tournament} &middot; {fmtTime(opp.start_time)}
          </p>
        </div>

        {/* Opportunity */}
        <Section>Opportunity</Section>
        <Row label="Side" value={opp.side} valueColor="#e2e8f0" />
        <Row label="Market Price" value={`${(opp.pm_price * 100).toFixed(1)}c`} />
        <Row label="True Probability" value={`${(opp.p_true * 100).toFixed(1)}%`} valueColor="#e2e8f0" />
        <div className="flex items-center justify-between py-2">
          <span className="font-mono text-[10px]" style={{ color: "#4b5563" }}>Edge</span>
          <span className="font-mono text-[14px] font-bold" style={{ color: edgeColor(opp.edge) }}>
            +{(opp.edge * 100).toFixed(2)}%
          </span>
        </div>
        <Row label="Kelly Size" value={opp.recommended_kelly > 0 ? `${(opp.recommended_kelly * 100).toFixed(2)}%` : "--"} valueColor="#38bdf8" />
        <Row
          label="Bet Size"
          value={opp.recommended_kelly > 0 ? `$${Math.round(bankroll * opp.recommended_kelly).toLocaleString()}` : "--"}
          valueColor={opp.recommended_kelly > 0 ? "#e2e8f0" : "#374151"}
        />

        {/* FanDuel Reference */}
        <Section>FanDuel Reference</Section>
        <Row label="Odds" value={fmtOdds(opp.fd_odds)} />
        <Row label="Overround" value={`${(opp.fanduel_overround * 100).toFixed(1)}%`} valueColor="#6b7280" />
        <div className="flex items-center justify-between py-1.5">
          <span className="font-mono text-[10px]" style={{ color: "#4b5563" }}>Line Width</span>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[10px]" style={{ color: lwColor }}>{(opp.fanduel_line_width * 100).toFixed(0)}%</span>
            <Badge label={opp.fanduel_line_width_label} color={lwColor} />
          </div>
        </div>
        <div className="flex items-center justify-between py-1.5">
          <span className="font-mono text-[10px]" style={{ color: "#4b5563" }}>Confidence</span>
          <Badge label={opp.fanduel_confidence_label} color={fdConfColor} />
        </div>

        {/* Match Quality */}
        <Section>Match Quality</Section>
        <Row label="Event Match" value={`${(opp.event_match_confidence * 100).toFixed(0)}%`} valueColor={opp.event_match_confidence >= 0.90 ? "#2dd4bf" : "#6b7280"} />
        <Row label="Type" value={typeLabel} valueColor="#38bdf8" />
        <Row label="Sport" value={sportLabel(opp.sport)} valueColor="#67e8f9" />
        <Row label="Exact Match" value="Yes" valueColor="#2dd4bf" />

        {/* Action */}
        <div className="pt-4 space-y-2">
          {opp.event_url ? (
            <a
              href={opp.event_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 w-full py-2.5 rounded-md border font-mono text-[10px] tracking-wider transition-all duration-150"
              style={{
                color: pColor,
                background: `${pColor}08`,
                borderColor: `${pColor}25`,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = `${pColor}15`;
                e.currentTarget.style.borderColor = `${pColor}40`;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = `${pColor}08`;
                e.currentTarget.style.borderColor = `${pColor}25`;
              }}
            >
              View on {platformLabel(opp.platform)}
              <svg width="9" height="9" viewBox="0 0 10 10" fill="none" style={{ opacity: 0.7 }}>
                <path d="M1 9L9 1M9 1H3M9 1V7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </a>
          ) : (
            <div
              className="flex items-center justify-center w-full py-2.5 rounded-md border font-mono text-[10px]"
              style={{ color: "#374151", background: "rgba(75,85,99,0.04)", borderColor: "rgba(75,85,99,0.15)" }}
            >
              No link available
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
