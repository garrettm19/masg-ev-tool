/**
 * Shared formatting + tone helpers for opportunity rows and cards.
 * Returns CSS var() references where colors are involved so callers can
 * drop them straight into inline styles without touching tokens.ts.
 */

import type { StatusPillTone, StatusPillVariant } from "@/app/components/ui/StatusPill";

export function fmtPct(n: number, dec = 1): string {
  return `${(n * 100).toFixed(dec)}%`;
}

export function fmtOdds(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${months[d.getMonth()]} ${d.getDate()}, ${hh}:${mm}`;
}

export function fmtAge(fetchedAt: number, nowSec: number): string {
  if (!fetchedAt || !nowSec) return "?";
  const sec = Math.max(0, Math.floor(nowSec - fetchedAt));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${Math.floor(sec / 3600)}h`;
}

/** Returns a CSS var() ref. <5min teal, <15min amber, else red. */
export function ageColor(fetchedAt: number, nowSec: number): string {
  if (!fetchedAt || !nowSec) return "var(--fg-faint)";
  const sec = nowSec - fetchedAt;
  if (sec < 300) return "var(--accent)";
  if (sec < 900) return "var(--warn-strong)";
  return "var(--danger-strong)";
}

export function platformLabel(p: string): string {
  if (p === "polymarket") return "Polymarket";
  if (p === "kalshi") return "Kalshi";
  return p.charAt(0).toUpperCase() + p.slice(1);
}

export function platformColor(p: string): string {
  if (p === "polymarket") return "var(--platform-polymarket)";
  if (p === "kalshi") return "var(--platform-kalshi)";
  return "var(--fg-secondary)";
}

/** Edge ramp -> CSS var. Aligned with --edge-* tokens in globals.css. */
export function edgeColor(edge: number): string {
  if (edge >= 0.10) return "var(--edge-elite)";
  if (edge >= 0.05) return "var(--edge-strong)";
  if (edge >= 0.02) return "var(--edge-soft)";
  return "var(--edge-mute)";
}

export interface StatusToneSpec {
  tone: StatusPillTone;
  variant: StatusPillVariant;
  title: string;
}

/** Single source of truth for BUY/WATCH/SKIP visual treatment + tooltip
 *  copy. Consumed by both OpportunityRow and OpportunityCard so the table
 *  and mobile views can never drift. */
export const STATUS_TONE: Record<string, StatusToneSpec> = {
  BUY:   { tone: "accent", variant: "solid",  title: "All rules pass — actionable per your criteria" },
  WATCH: { tone: "info",   variant: "dashed", title: "Watch only — not actionable. A downgrade rule failed." },
  SKIP:  { tone: "muted",  variant: "solid",  title: "Skipped — a critical rule failed" },
};
