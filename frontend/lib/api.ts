import { OpportunitiesResponse, SnapshotStatus, SportDataStatus } from "./types";
import type { SportRegistryEntry } from "./sport-labels";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export interface PriceHistoryResponse {
  platform: string;
  market_id: string;
  points: { t: number; p: number }[];
  count: number;
}

export async function fetchPriceHistory(
  platform: string,
  marketId: string,
): Promise<PriceHistoryResponse> {
  const url = new URL(`${BACKEND_URL}/api/opportunities/history`);
  url.searchParams.set("platform", platform);
  url.searchParams.set("market_id", marketId);
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend error: ${res.status}`);
  return res.json();
}

export async function fetchOpportunities(params: {
  platform?: string;
  include_watch?: boolean;
} = {}): Promise<OpportunitiesResponse> {
  const url = new URL(`${BACKEND_URL}/api/opportunities`);
  if (params.platform != null) url.searchParams.set("platform", params.platform);
  if (params.include_watch != null) url.searchParams.set("include_watch", String(params.include_watch));
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend error: ${res.status}`);
  return res.json();
}

export async function fetchSnapshotStatus(): Promise<SnapshotStatus> {
  const res = await fetch(`${BACKEND_URL}/api/opportunities/status`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend error: ${res.status}`);
  return res.json();
}

export async function fetchSnapshot(): Promise<OpportunitiesResponse | null> {
  const res = await fetch(`${BACKEND_URL}/api/opportunities/snapshot`, { cache: "no-store" });
  if (res.status === 204) return null;
  if (!res.ok) throw new Error(`Backend error: ${res.status}`);
  return res.json();
}

export async function refreshOpportunities(): Promise<SnapshotStatus> {
  const res = await fetch(`${BACKEND_URL}/api/opportunities/refresh`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Backend error: ${res.status}`);
  }
  return res.json();
}

export async function fetchSportsRegistry(): Promise<Record<string, SportRegistryEntry>> {
  const res = await fetch(`${BACKEND_URL}/api/sports`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend error: ${res.status}`);
  return res.json();
}

export async function fetchDataStatus(): Promise<SportDataStatus[]> {
  const res = await fetch(`${BACKEND_URL}/api/data-status`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend error: ${res.status}`);
  return res.json();
}

export interface HistoricalOddsSnapshot {
  event_id: string;
  home_team: string;
  away_team: string;
  home_odds: number;
  away_odds: number;
  draw_odds: number | null;
  snapshot_time: string;
  home_implied: number;
  away_implied: number;
}

export async function fetchHistoricalOdds(
  sportKey: string,
  eventId: string,
  date: string,
): Promise<HistoricalOddsSnapshot | null> {
  const url = new URL(`${BACKEND_URL}/api/opportunities/historical-odds`);
  url.searchParams.set("sport_key", sportKey);
  url.searchParams.set("event_id", eventId);
  url.searchParams.set("date", date);
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) return null;
  const body = await res.json();
  return body.snapshot ?? null;
}

