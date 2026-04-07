"use client";

import { useState, useCallback, useEffect } from "react";
import { Opportunity, TrackedPosition } from "./types";

const STORAGE_KEY = "masg_tracked_positions";

function loadPositions(): TrackedPosition[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function savePositions(positions: TrackedPosition[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(positions));
  } catch {
    // storage full or unavailable
  }
}

function positionId(opp: Opportunity): string {
  return `${opp.platform}:${opp.market_id}:${opp.side}`;
}

export function useTrackedPositions() {
  const [positions, setPositions] = useState<TrackedPosition[]>([]);

  // Load from localStorage on mount
  useEffect(() => {
    setPositions(loadPositions());
  }, []);

  const takenIds = new Set(positions.map((p) => p.id));

  const isTaken = useCallback(
    (opp: Opportunity) => takenIds.has(positionId(opp)),
    [takenIds],
  );

  const takePosition = useCallback(
    (opp: Opportunity) => {
      const id = positionId(opp);
      if (takenIds.has(id)) return;

      const pos: TrackedPosition = {
        id,
        market_id: opp.market_id,
        platform: opp.platform,
        sport: opp.sport,
        event: opp.event,
        event_url: opp.event_url,
        market_type: opp.market_type,
        side: opp.side,
        line: opp.line,
        entry_price: opp.pm_price,
        entry_edge: opp.edge,
        entry_kelly: opp.recommended_kelly,
        fd_odds: opp.fd_odds,
        p_true: opp.p_true,
        taken_at: new Date().toISOString(),
        status: "open",
      };

      const next = [pos, ...positions];
      setPositions(next);
      savePositions(next);
    },
    [positions, takenIds],
  );

  const closePosition = useCallback(
    (id: string) => {
      const next = positions.map((p) =>
        p.id === id ? { ...p, status: "closed" as const } : p,
      );
      setPositions(next);
      savePositions(next);
    },
    [positions],
  );

  const removePosition = useCallback(
    (id: string) => {
      const next = positions.filter((p) => p.id !== id);
      setPositions(next);
      savePositions(next);
    },
    [positions],
  );

  return { positions, isTaken, takePosition, closePosition, removePosition };
}
