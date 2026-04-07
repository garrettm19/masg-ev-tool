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
  min_edge?: number;
  wide_market_min_edge?: number;
  survival_threshold?: number;
  buy_threshold?: number;
  min_true_probability?: number;
  platform?: string;
  include_watch?: boolean;
} = {}): Promise<OpportunitiesResponse> {
  const url = new URL(`${BACKEND_URL}/api/opportunities`);
  if (params.min_edge != null) url.searchParams.set("min_edge", String(params.min_edge));
  if (params.wide_market_min_edge != null) url.searchParams.set("wide_market_min_edge", String(params.wide_market_min_edge));
  if (params.survival_threshold != null) url.searchParams.set("survival_threshold", String(params.survival_threshold));
  if (params.buy_threshold != null) url.searchParams.set("buy_threshold", String(params.buy_threshold));
  if (params.min_true_probability != null) url.searchParams.set("min_true_probability", String(params.min_true_probability));
  if (params.platform != null) url.searchParams.set("platform", params.platform);
  if (params.include_watch != null) url.searchParams.set("include_watch", String(params.include_watch));
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend error: ${res.status}`);
  return res.json();
}
