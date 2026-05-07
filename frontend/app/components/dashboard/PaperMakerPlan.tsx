"use client";

import { useEffect, useState } from "react";
import type { MakerProposal } from "@/lib/types";
import { fetchMakerProposals } from "@/lib/api";
import { Badge } from "../ui/Badge";

interface Props {
  marketId: string;
  side: string;
}

// ---------------------------------------------------------------------------
// Local helpers — keep parallel to MarketDetailPanel's Row/Section so the
// section reads consistently with the rest of the panel without coupling
// to that component's private internals.
// ---------------------------------------------------------------------------

function Section({ children }: { children: string }) {
  return (
    <p
      className="font-mono uppercase tracking-[0.12em] pt-4 pb-1.5 font-medium"
      style={{ fontSize: "9px", color: "var(--accent)", opacity: 0.6 }}
    >
      {children}
    </p>
  );
}

function Row({
  label,
  value,
  valueColor = "var(--fg-secondary)",
  title,
}: {
  label: string;
  value: string;
  valueColor?: string;
  title?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5" title={title}>
      <span className="font-mono" style={{ fontSize: "10px", color: "var(--fg-faint)" }}>
        {label}
      </span>
      <span
        className="font-mono font-medium"
        style={{ fontSize: "11px", color: valueColor, fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </span>
    </div>
  );
}

function fmtCents(price: number | null): string {
  if (price == null) return "—";
  return `${(price * 100).toFixed(1)}¢`;
}

function fmtPct(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`;
}

// Null-safe edge formatter for rejected proposals where estimated_maker_edge
// is None whenever proposed_price is None.  Includes the leading "+" only
// for real numeric values; missing values render as "—".
function fmtEdgeSigned(edge: number | null): string {
  if (edge == null) return "—";
  return `+${fmtPct(edge)}`;
}

function makerEdgeColor(edge: number | null): string {
  if (edge == null) return "var(--edge-mute)";
  if (edge >= 0.10) return "var(--edge-elite)";
  if (edge >= 0.05) return "var(--edge-strong)";
  if (edge >= 0.02) return "var(--edge-soft)";
  return "var(--edge-mute)";
}

// ---------------------------------------------------------------------------
// Match a proposal to the selected opportunity by (market_id, side), taking
// the most recent record by created_at when multiple exist.
// ---------------------------------------------------------------------------

function selectProposal(
  proposals: MakerProposal[],
  marketId: string,
  side: string,
): MakerProposal | null {
  const matches = proposals
    .filter((p) => p.market_id === marketId && p.side === side)
    .sort((a, b) => b.created_at - a.created_at);
  return matches[0] ?? null;
}

// ---------------------------------------------------------------------------
// Eligible — prominent suggested bid + maker edge, locked PAPER ONLY badge.
// Never includes a "place order" affordance.  Visual language matches the
// existing Tracked-position chip palette so paper records are unmistakably
// non-actionable.
// ---------------------------------------------------------------------------

function executionRouteText(p: MakerProposal): string {
  const ticker = p.execution_market_id || p.market_id;
  const side = p.execution_contract_side ?? "yes";
  // Equivalent-NO routes target the OPPOSING ticker's NO contract.  Direct
  // YES routes target the canonical ticker's YES contract.
  const sideLabel = side === "no" ? "NO" : "YES";
  const suffix = side === "no" ? " (equivalent)" : "";
  return `${sideLabel} on ${ticker}${suffix}`;
}

function EligibleProposal({ p }: { p: MakerProposal }) {
  const edgeColor = makerEdgeColor(p.estimated_maker_edge);
  const showTakeNotMakeNote = p.notes.some((n) => n.includes("TAKE_NOT_MAKE"));
  const isEquivalentNo = (p.execution_contract_side ?? "yes") === "no";

  return (
    <>
      <Section>Paper Maker Plan</Section>

      <div
        className="rounded-md border p-3 mt-1"
        style={{
          background: "var(--warn-soft)",
          borderColor: "var(--warn-border)",
          borderRadius: "var(--radius-md)",
        }}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <span
            className="font-mono uppercase tracking-[0.15em] font-medium"
            style={{ fontSize: "8px", color: "var(--warn-strong)" }}
          >
            Paper Only · Eligible
          </span>
          <Badge label="PAPER" variant="warn" />
        </div>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <p
              className="font-mono uppercase tracking-[0.15em]"
              style={{ fontSize: "8px", color: "var(--fg-faint)" }}
            >
              Suggested Bid
            </p>
            <p
              className="font-mono font-bold"
              style={{
                fontSize: "20px",
                color: "var(--fg-primary)",
                lineHeight: 1.1,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmtCents(p.proposed_price)}
            </p>
          </div>
          <div className="text-right">
            <p
              className="font-mono uppercase tracking-[0.15em]"
              style={{ fontSize: "8px", color: "var(--fg-faint)" }}
            >
              Maker Edge
            </p>
            <p
              className="font-mono font-bold"
              style={{
                fontSize: "20px",
                color: edgeColor,
                lineHeight: 1.1,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmtEdgeSigned(p.estimated_maker_edge)}
            </p>
          </div>
        </div>

        <Row
          label="Paper Route"
          value={executionRouteText(p)}
          valueColor={isEquivalentNo ? "var(--info)" : "var(--fg-secondary)"}
          title={
            isEquivalentNo
              ? "Equivalent route: posting NO on the opposing ticker is economically identical to YES on this team in 2-way."
              : "Direct YES bid on the team's own ticker."
          }
        />
        <Row label="Best Bid" value={fmtCents(p.best_bid)} />
        <Row label="Best Ask" value={fmtCents(p.best_ask)} />
        <Row
          label="Maker Max Bid"
          value={fmtCents(p.maker_max_bid)}
          title="p_true − required_edge − cost_buffer (rounded down to tick)"
        />
        <Row
          label="Required Edge"
          value={`+${fmtPct(p.required_edge)}`}
          title="Sport-specific minimum edge for BUY-equivalent eligibility"
        />
        <Row label="Cost Buffer" value={fmtCents(p.cost_buffer)} />

        <Row
          label="Taker Status"
          value={p.taker_status_at_planning || "—"}
          valueColor={
            p.taker_status_at_planning === "BUY"
              ? "var(--accent)"
              : p.taker_status_at_planning === "WATCH"
                ? "var(--info)"
                : "var(--fg-muted)"
          }
        />
        {p.taker_reject_reasons.length > 0 && (
          <Row
            label="Taker Rejected"
            value={p.taker_reject_reasons.join(", ")}
            valueColor="var(--fg-muted)"
            title="Why the existing taker scanner skipped this candidate"
          />
        )}

        {showTakeNotMakeNote && (
          <p
            className="font-mono italic mt-3"
            style={{ fontSize: "10px", color: "var(--info)" }}
          >
            Note: the current ask itself would clear the required edge — the
            existing taker scanner already covers that case.
          </p>
        )}

        <p
          className="font-mono mt-3"
          style={{ fontSize: "10px", color: "var(--warn-strong)" }}
        >
          This is a paper proposal, not an order.
        </p>
        <p
          className="font-mono italic mt-1"
          style={{ fontSize: "9px", color: "var(--fg-muted)" }}
        >
          Maker fills are not guaranteed and may occur when the market is
          moving against you.
        </p>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Rejected — show why, no prominent number, still PAPER ONLY.
// ---------------------------------------------------------------------------

function RejectedProposal({ p }: { p: MakerProposal }) {
  const showBookData = p.best_bid != null || p.best_ask != null;

  return (
    <>
      <Section>Paper Maker Plan</Section>

      <div
        className="rounded-md border p-3 mt-1"
        style={{
          background: "rgba(75,85,99,0.04)",
          borderColor: "var(--border-subtle)",
          borderRadius: "var(--radius-md)",
        }}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <span
            className="font-mono uppercase tracking-[0.15em] font-medium"
            style={{ fontSize: "8px", color: "var(--fg-muted)" }}
          >
            Paper Only · Rejected
          </span>
          <Badge label="PAPER" variant="warn" />
        </div>

        {p.rejection_reasons.length > 0 && (
          <div className="mb-3">
            <p
              className="font-mono uppercase tracking-[0.12em] mb-1"
              style={{ fontSize: "9px", color: "var(--fg-faint)" }}
            >
              Reasons
            </p>
            <ul className="space-y-1">
              {p.rejection_reasons.map((reason, i) => (
                <li key={`${reason}-${i}`} className="flex items-start gap-2">
                  <span
                    className="font-mono shrink-0"
                    style={{ fontSize: "10px", color: "var(--warn-strong)", lineHeight: 1.4 }}
                    aria-hidden="true"
                  >
                    ⚠
                  </span>
                  <span
                    className="font-mono"
                    style={{ fontSize: "10px", color: "var(--warn-strong)", lineHeight: 1.4 }}
                  >
                    {reason}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {showBookData && (
          <>
            <Row
              label="Paper Route"
              value={executionRouteText(p)}
              valueColor="var(--fg-muted)"
            />
            <Row label="Best Bid" value={fmtCents(p.best_bid)} />
            <Row label="Best Ask" value={fmtCents(p.best_ask)} />
            <Row label="Maker Max Bid" value={fmtCents(p.maker_max_bid)} />
            <Row
              label="Estimated Edge"
              value={fmtEdgeSigned(p.estimated_maker_edge)}
              valueColor="var(--fg-muted)"
            />
          </>
        )}

        <Row
          label="Taker Status"
          value={p.taker_status_at_planning || "—"}
          valueColor="var(--fg-muted)"
        />

        <p
          className="font-mono italic mt-3"
          style={{ fontSize: "10px", color: "var(--fg-muted)" }}
        >
          This is a paper proposal, not an order.
        </p>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Hidden when there's no proposal — render a small muted line so the
// section still anchors visually but doesn't shout.
// ---------------------------------------------------------------------------

function NoProposalLine() {
  return (
    <>
      <Section>Paper Maker Plan</Section>
      <p
        className="font-mono italic py-1.5"
        style={{ fontSize: "10px", color: "var(--fg-ghost)" }}
      >
        No paper maker plan for this opportunity.
      </p>
    </>
  );
}

// ---------------------------------------------------------------------------
// Public entry — fetches its own proposal data when the selected
// (marketId, side) changes.  Read-only; never mutates server state.
// ---------------------------------------------------------------------------

export function PaperMakerPlan({ marketId, side }: Props) {
  const [proposal, setProposal] = useState<MakerProposal | null>(null);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErrored(false);
    // latest_run narrows the response to the most recent scan only — the
    // audit JSONL accumulates records across many refreshes, but the
    // detail panel should reflect the planner's view from the freshest
    // scan to avoid showing stale prices/route info.
    fetchMakerProposals({ days: 1, market_id: marketId, latest_run: true })
      .then((resp) => {
        if (cancelled) return;
        setProposal(selectProposal(resp.proposals, marketId, side));
      })
      .catch(() => {
        if (cancelled) return;
        setErrored(true);
        setProposal(null);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [marketId, side]);

  if (loading) return null;
  if (errored) return null;          // Silent on backend error — never show a noisy panel
  if (!proposal) return <NoProposalLine />;

  return proposal.eligible ? <EligibleProposal p={proposal} /> : <RejectedProposal p={proposal} />;
}
