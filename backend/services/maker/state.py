"""
Paper-only persistence for maker proposals.

Every ``MakerProposal`` produced by the planner — eligible or rejected —
is appended as a single JSONL record under
``backend/data/maker_paper_orders/YYYY-MM-DD.jsonl``.  The day is derived
from the proposal's ``created_at`` so all records for one day land in the
same file regardless of when the process started.

The store is read-only with respect to external services.  No secrets are
stored: ``MakerProposal`` carries no API keys, and the serializer copies
only its public fields.

Lifecycle statuses (declared here, written by the service / future
fill simulator):

    proposed             — initial state before any policy verdict
    paper_active         — eligible proposal accepted into paper book
    paper_rejected       — ineligible proposal, kept for audit
    paper_expired        — TTL elapsed (future fill simulator)
    paper_cancelled      — pre-event cancel (future fill simulator)
    paper_invalidated    — book moved through us (future fill simulator)
    paper_filled         — paper fill recorded (future fill simulator)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from services.maker.planner import MakerProposal

logger = logging.getLogger(__name__)

# Lifecycle status constants.  Service uses paper_active / paper_rejected
# in v1; the rest are reserved for the future fill simulator.
STATUS_PROPOSED = "proposed"
STATUS_PAPER_ACTIVE = "paper_active"
STATUS_PAPER_REJECTED = "paper_rejected"
STATUS_PAPER_EXPIRED = "paper_expired"
STATUS_PAPER_CANCELLED = "paper_cancelled"
STATUS_PAPER_INVALIDATED = "paper_invalidated"
STATUS_PAPER_FILLED = "paper_filled"

ALL_STATUSES: frozenset[str] = frozenset({
    STATUS_PROPOSED,
    STATUS_PAPER_ACTIVE,
    STATUS_PAPER_REJECTED,
    STATUS_PAPER_EXPIRED,
    STATUS_PAPER_CANCELLED,
    STATUS_PAPER_INVALIDATED,
    STATUS_PAPER_FILLED,
})

SCHEMA_VERSION = 1

# Default storage location: backend/data/maker_paper_orders.  Relative to
# this file, two levels up matches the existing alert_state convention.
_DEFAULT_BASE_DIR = Path(os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "maker_paper_orders"
)).resolve()


def _proposal_to_record(proposal: MakerProposal, status: str) -> dict:
    """Serialize a ``MakerProposal`` plus a status into a JSON-ready dict.

    Copies only public proposal fields — no API keys, no secrets, no
    file paths.  Tuples are flattened to lists so json.dumps round-trips
    cleanly.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "proposal_id": proposal.proposal_id,
        "platform": proposal.platform,
        "market_id": proposal.market_id,
        "market_type": proposal.market_type,
        "side": proposal.side,
        "event_label": proposal.event_label,
        "event_start": proposal.event_start,
        # Snapshot
        "p_true": proposal.p_true,
        "required_edge": proposal.required_edge,
        "cost_buffer": proposal.cost_buffer,
        "best_bid": proposal.best_bid,
        "best_ask": proposal.best_ask,
        "book_fetched_at": proposal.book_fetched_at,
        "fd_fetched_at": proposal.fd_fetched_at,
        # Math
        "maker_max_bid": proposal.maker_max_bid,
        "proposed_price": proposal.proposed_price,
        "tick_size": proposal.tick_size,
        "estimated_maker_edge": proposal.estimated_maker_edge,
        # Eligibility
        "eligible": proposal.eligible,
        "rejection_reasons": list(proposal.rejection_reasons),
        "rule_evaluations": [
            {
                "rule_name": r.rule_name,
                "passed": r.passed,
                "severity": r.severity,
                "reason_code": r.reason_code,
                "description": r.description,
            }
            for r in proposal.rule_evaluations
        ],
        # Provenance — taker classification at planning time (audit only)
        "taker_status_at_planning": proposal.taker_status_at_planning,
        "taker_reject_reasons": list(proposal.taker_reject_reasons),
        "taker_downgrade_reasons": list(proposal.taker_downgrade_reasons),
        "taker_edge_at_planning": proposal.taker_edge_at_planning,
        # Audit
        "created_at": proposal.created_at,
        "notes": list(proposal.notes),
        # Display + execution route (legacy records may lack these — readers
        # should treat missing values as "direct_yes on market_id").
        "display_side": proposal.display_side,
        "execution_market_id": proposal.execution_market_id,
        "execution_contract_side": proposal.execution_contract_side,
        "execution_route": proposal.execution_route,
    }


def _day_from_created_at(created_at: float) -> date:
    """UTC date of the proposal's ``created_at`` timestamp."""
    return datetime.fromtimestamp(created_at, tz=timezone.utc).date()


class PaperMakerStore:
    """Append-only JSONL store for paper maker proposals.

    File layout:
        ``<base_dir>/YYYY-MM-DD.jsonl`` — one JSON record per line.

    All writes are append-only; the file is opened with mode ``"a"``.  The
    parent directory is created lazily on first write.  Reads tolerate
    missing files (returning ``[]``) and skip individual malformed lines.
    """

    def __init__(self, base_dir: Path | str | None = None):
        if base_dir is None:
            self.base_dir = _DEFAULT_BASE_DIR
        else:
            self.base_dir = Path(base_dir)

    # --- Paths ---

    def path_for(self, day: date) -> Path:
        return self.base_dir / f"{day.isoformat()}.jsonl"

    # --- Writes ---

    def append(self, proposal: MakerProposal, status: str) -> Path:
        """Append one proposal record (with status) to its day file.

        Returns the path written.  Status must be one of ``ALL_STATUSES``.
        """
        if status not in ALL_STATUSES:
            raise ValueError(
                f"unknown maker proposal status: {status!r} "
                f"(allowed: {sorted(ALL_STATUSES)})"
            )

        record = _proposal_to_record(proposal, status)
        day = _day_from_created_at(proposal.created_at)
        path = self.path_for(day)

        # Lazy mkdir — only when actually writing.
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return path

    # --- Reads ---

    def read_day(self, day: date) -> list[dict]:
        """Read all records for one day.  Returns ``[]`` if the file is
        missing.  Skips malformed lines with a logged warning."""
        path = self.path_for(day)
        if not path.exists():
            return []
        records: list[dict] = []
        with open(path, "r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "PaperMakerStore: skipping corrupt line %d in %s: %s",
                        lineno, path, exc,
                    )
                    continue
        return records

    def read_recent(self, days: int = 7) -> list[dict]:
        """Read records across the most recent ``days`` UTC days, newest day last.

        Returns an empty list if the directory doesn't exist or no files
        match.  Days with no file simply contribute nothing.
        """
        if days <= 0:
            return []
        out: list[dict] = []
        today = datetime.now(tz=timezone.utc).date()
        for delta in range(days - 1, -1, -1):  # oldest first → newest last
            d = date.fromordinal(today.toordinal() - delta)
            out.extend(self.read_day(d))
        return out

    def iter_day(self, day: date) -> Iterator[dict]:
        """Generator variant of ``read_day`` — useful for large files."""
        path = self.path_for(day)
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "PaperMakerStore: skipping corrupt line %d in %s: %s",
                        lineno, path, exc,
                    )
                    continue
