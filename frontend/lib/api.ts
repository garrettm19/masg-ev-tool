import { OpportunitiesResponse } from "./types";

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
