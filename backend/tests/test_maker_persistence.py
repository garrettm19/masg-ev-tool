"""
Tests for the paper maker proposal store (services/maker/state.py).

Persistence is JSONL, append-only, one file per UTC date derived from
the proposal's ``created_at``.  These tests use ``tmp_path`` fixtures
exclusively — no writes to the real ``backend/data/`` directory.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.maker.state import (
    ALL_STATUSES,
    PaperMakerStore,
    SCHEMA_VERSION,
    STATUS_PAPER_ACTIVE,
    STATUS_PAPER_REJECTED,
    _proposal_to_record,
)
from services.rule_engine import RuleResult
from services.maker.planner import MakerProposal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proposal(
    *,
    eligible: bool = True,
    rejection_reasons: tuple[str, ...] = (),
    created_at: float | None = None,
    proposal_id: str = "p-test-1",
    notes: tuple[str, ...] = ("paper_only",),
    **overrides,
) -> MakerProposal:
    """Minimal MakerProposal for persistence tests — every field set."""
    if created_at is None:
        created_at = time.time()
    base = dict(
        proposal_id=proposal_id,
        platform="kalshi",
        market_id="K1",
        market_type="h2h",
        side="A",
        event_label="A vs B",
        event_start="2099-01-01T00:00:00Z",
        p_true=0.50,
        required_edge=0.05,
        cost_buffer=0.01,
        best_bid=0.40,
        best_ask=0.90,
        book_fetched_at=created_at,
        fd_fetched_at=created_at,
        maker_max_bid=0.44,
        proposed_price=0.41,
        tick_size=0.01,
        estimated_maker_edge=0.08,
        eligible=eligible,
        rejection_reasons=rejection_reasons,
        rule_evaluations=(
            RuleResult(
                rule_name="name_match",
                passed=True,
                severity="CRITICAL",
                reason_code="NAME_MISMATCH",
                description="ok",
            ),
        ),
        taker_status_at_planning="SKIP",
        taker_reject_reasons=("NO_EDGE",),
        taker_downgrade_reasons=(),
        taker_edge_at_planning=-0.41,
        created_at=created_at,
        notes=notes,
    )
    base.update(overrides)
    return MakerProposal(**base)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_append_and_read_back(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal(proposal_id="round-trip-1")
        path = store.append(prop, STATUS_PAPER_ACTIVE)

        assert path.parent == tmp_path
        records = store.read_day(
            datetime.fromtimestamp(prop.created_at, tz=timezone.utc).date()
        )
        assert len(records) == 1
        rec = records[0]
        assert rec["proposal_id"] == "round-trip-1"
        assert rec["status"] == STATUS_PAPER_ACTIVE
        assert rec["schema_version"] == SCHEMA_VERSION

    def test_eligible_persisted_as_paper_active(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal(eligible=True)
        store.append(prop, STATUS_PAPER_ACTIVE)

        day = datetime.fromtimestamp(prop.created_at, tz=timezone.utc).date()
        records = store.read_day(day)
        assert records[0]["status"] == STATUS_PAPER_ACTIVE
        assert records[0]["eligible"] is True
        assert records[0]["rejection_reasons"] == []

    def test_rejected_persisted_with_reasons(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal(
            eligible=False,
            rejection_reasons=("PLATFORM_OUT_OF_SCOPE", "BOOK_STALE"),
        )
        store.append(prop, STATUS_PAPER_REJECTED)

        day = datetime.fromtimestamp(prop.created_at, tz=timezone.utc).date()
        records = store.read_day(day)
        assert records[0]["status"] == STATUS_PAPER_REJECTED
        assert records[0]["eligible"] is False
        assert records[0]["rejection_reasons"] == [
            "PLATFORM_OUT_OF_SCOPE",
            "BOOK_STALE",
        ]


# ---------------------------------------------------------------------------
# Audit fields
# ---------------------------------------------------------------------------

class TestAuditFields:
    REQUIRED_FIELDS = {
        "schema_version",
        "status",
        "proposal_id",
        "platform",
        "market_id",
        "market_type",
        "side",
        "event_label",
        "event_start",
        "p_true",
        "required_edge",
        "cost_buffer",
        "best_bid",
        "best_ask",
        "book_fetched_at",
        "fd_fetched_at",
        "maker_max_bid",
        "proposed_price",
        "tick_size",
        "estimated_maker_edge",
        "eligible",
        "rejection_reasons",
        "rule_evaluations",
        "taker_status_at_planning",
        "taker_reject_reasons",
        "taker_downgrade_reasons",
        "taker_edge_at_planning",
        "created_at",
        "notes",
        # Execution route — disambiguates 2-way Kalshi market_id/side
        "display_side",
        "execution_market_id",
        "execution_contract_side",
        "execution_route",
    }

    def test_record_has_all_required_fields(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()
        store.append(prop, STATUS_PAPER_ACTIVE)
        records = store.read_recent(days=2)
        assert records, "expected at least one record"
        rec = records[-1]
        assert set(rec.keys()) >= self.REQUIRED_FIELDS

    def test_rule_evaluations_serialize_dataclasses_to_dicts(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()
        store.append(prop, STATUS_PAPER_ACTIVE)
        records = store.read_recent(days=2)
        evals = records[-1]["rule_evaluations"]
        assert isinstance(evals, list)
        assert all(isinstance(e, dict) for e in evals)
        # Each entry has the RuleResult shape
        for e in evals:
            assert set(e.keys()) == {
                "rule_name", "passed", "severity", "reason_code", "description",
            }

    def test_no_secrets_persisted(self, tmp_path: Path, monkeypatch):
        """Sanity check: serialized record contains no api-key-shaped values
        even when KALSHI_API_KEY is set in the environment."""
        monkeypatch.setenv("KALSHI_API_KEY", "secret-XYZ-123")
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()
        path = store.append(prop, STATUS_PAPER_ACTIVE)

        raw = path.read_text(encoding="utf-8")
        assert "secret-XYZ-123" not in raw
        assert "api_key" not in raw
        assert "KALSHI_API_KEY" not in raw
        assert "Authorization" not in raw

    def test_record_round_trips_through_json(self, tmp_path: Path):
        """Every value must be JSON-serializable.  No tuples, no dataclasses."""
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()
        path = store.append(prop, STATUS_PAPER_ACTIVE)

        raw = path.read_text(encoding="utf-8").strip()
        parsed = json.loads(raw)
        # The parsed dict must equal the in-memory serialized dict exactly.
        assert parsed == _proposal_to_record(prop, STATUS_PAPER_ACTIVE)


# ---------------------------------------------------------------------------
# File / directory handling
# ---------------------------------------------------------------------------

class TestFileHandling:
    def test_missing_directory_is_created(self, tmp_path: Path):
        target = tmp_path / "nested" / "subdir"
        assert not target.exists()
        store = PaperMakerStore(base_dir=target)
        store.append(_proposal(), STATUS_PAPER_ACTIVE)
        assert target.exists()
        # The day file is inside it
        files = list(target.glob("*.jsonl"))
        assert len(files) == 1

    def test_multiple_proposals_same_day_append(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        ts = time.time()
        store.append(_proposal(proposal_id="a", created_at=ts), STATUS_PAPER_ACTIVE)
        store.append(_proposal(proposal_id="b", created_at=ts), STATUS_PAPER_REJECTED)
        store.append(_proposal(proposal_id="c", created_at=ts), STATUS_PAPER_ACTIVE)

        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        records = store.read_day(day)
        assert [r["proposal_id"] for r in records] == ["a", "b", "c"]
        assert [r["status"] for r in records] == [
            STATUS_PAPER_ACTIVE,
            STATUS_PAPER_REJECTED,
            STATUS_PAPER_ACTIVE,
        ]

    def test_day_based_file_selection(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        # Two proposals on different UTC days
        day1_ts = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc).timestamp()
        day2_ts = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc).timestamp()
        store.append(_proposal(proposal_id="d1", created_at=day1_ts), STATUS_PAPER_ACTIVE)
        store.append(_proposal(proposal_id="d2", created_at=day2_ts), STATUS_PAPER_ACTIVE)

        d1 = store.read_day(datetime.fromtimestamp(day1_ts, tz=timezone.utc).date())
        d2 = store.read_day(datetime.fromtimestamp(day2_ts, tz=timezone.utc).date())
        assert [r["proposal_id"] for r in d1] == ["d1"]
        assert [r["proposal_id"] for r in d2] == ["d2"]

        # Files are named by ISO date
        files = sorted(p.name for p in tmp_path.glob("*.jsonl"))
        assert files == ["2026-05-06.jsonl", "2026-05-07.jsonl"]

    def test_read_day_missing_returns_empty(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        assert store.read_day(datetime(2099, 1, 1, tzinfo=timezone.utc).date()) == []

    def test_read_recent_missing_dir_returns_empty(self, tmp_path: Path):
        target = tmp_path / "does_not_exist"
        store = PaperMakerStore(base_dir=target)
        assert store.read_recent(days=7) == []

    def test_corrupt_line_skipped(self, tmp_path: Path):
        """A corrupt JSON line in the middle of a file is skipped, not crashing
        the whole read."""
        store = PaperMakerStore(base_dir=tmp_path)
        ts = time.time()
        store.append(_proposal(proposal_id="ok-1", created_at=ts), STATUS_PAPER_ACTIVE)

        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        path = store.path_for(day)
        # Manually splice a corrupt line in
        with open(path, "a", encoding="utf-8") as f:
            f.write("{bogus json without closing brace\n")
            f.write("not even close to json\n")

        store.append(_proposal(proposal_id="ok-2", created_at=ts), STATUS_PAPER_ACTIVE)

        records = store.read_day(day)
        ids = [r["proposal_id"] for r in records]
        assert ids == ["ok-1", "ok-2"]

    def test_blank_lines_ignored(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        ts = time.time()
        store.append(_proposal(proposal_id="ok-1", created_at=ts), STATUS_PAPER_ACTIVE)

        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        path = store.path_for(day)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n\n   \n")

        records = store.read_day(day)
        assert len(records) == 1


# ---------------------------------------------------------------------------
# Status validation
# ---------------------------------------------------------------------------

class TestStatusValidation:
    def test_rejects_unknown_status(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        with pytest.raises(ValueError):
            store.append(_proposal(), "bogus_status")

    def test_all_lifecycle_statuses_accepted(self, tmp_path: Path):
        """Every documented lifecycle status must be writable.  Sanity check
        in case a future commit narrows the allow-list by accident."""
        store = PaperMakerStore(base_dir=tmp_path)
        ts = time.time()
        for i, status in enumerate(sorted(ALL_STATUSES)):
            store.append(_proposal(proposal_id=f"p-{i}", created_at=ts), status)

        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        records = store.read_day(day)
        assert {r["status"] for r in records} == set(ALL_STATUSES)


# ---------------------------------------------------------------------------
# Iterator
# ---------------------------------------------------------------------------

class TestNullablePriceFieldsPersistence:
    """Rejected proposals can carry None for ``maker_max_bid`` /
    ``proposed_price`` / ``estimated_maker_edge`` when the math cannot
    produce a realizable bid (low p_true, missing book).  These None
    values must round-trip through JSONL as JSON null and parse back as
    None — never as 0, "—", or the string "None"."""

    def test_none_proposed_price_persists_as_json_null(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal(
            eligible=False,
            rejection_reasons=("TRUE_PROB_TOO_LOW", "BOOK_CROSSED_OR_EMPTY"),
            maker_max_bid=None,
            proposed_price=None,
            estimated_maker_edge=None,
        )
        path = store.append(prop, STATUS_PAPER_REJECTED)
        raw = path.read_text(encoding="utf-8").strip()
        # JSON null literal, not the string "null" or 0
        assert '"maker_max_bid":null' in raw
        assert '"proposed_price":null' in raw
        assert '"estimated_maker_edge":null' in raw
        # No negative cents anywhere in the persisted payload
        assert "-0.01" not in raw

    def test_none_proposed_price_round_trips_to_python_none(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal(
            eligible=False,
            rejection_reasons=("BOOK_CROSSED_OR_EMPTY",),
            maker_max_bid=None,
            proposed_price=None,
            estimated_maker_edge=None,
        )
        store.append(prop, STATUS_PAPER_REJECTED)
        rec = store.read_recent(days=2)[0]
        assert rec["maker_max_bid"] is None
        assert rec["proposed_price"] is None
        assert rec["estimated_maker_edge"] is None

    def test_eligible_record_keeps_concrete_numbers(self, tmp_path: Path):
        """Sanity: eligible records still persist concrete float values for
        the three price-shaped fields (the eligible invariant)."""
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()  # default factory: 0.41 / 0.44 / 0.08
        store.append(prop, STATUS_PAPER_ACTIVE)
        rec = store.read_recent(days=2)[0]
        assert rec["proposed_price"] == 0.41
        assert rec["maker_max_bid"] == 0.44
        assert rec["estimated_maker_edge"] == 0.08


class TestRunIdPersistence:
    """``run_id`` round-trips through JSONL, including legacy records that
    predate the field (which serialize as ``null`` because the dataclass
    default is ``None``)."""

    def test_run_id_round_trips(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()
        with_run = MakerProposal(**{
            **{f.name: getattr(prop, f.name)
               for f in prop.__dataclass_fields__.values()},
            "run_id": "11111111-2222-3333-4444-555555555555",
        })
        store.append(with_run, STATUS_PAPER_ACTIVE)
        rec = store.read_recent(days=2)[0]
        assert rec["run_id"] == "11111111-2222-3333-4444-555555555555"

    def test_default_run_id_serializes_as_null(self, tmp_path: Path):
        """Unit-test fixtures that don't set run_id leave the dataclass
        default (None) in place; persistence must serialize it as JSON
        null, never as the string ``"None"``."""
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()  # default factory leaves run_id=None
        path = store.append(prop, STATUS_PAPER_ACTIVE)
        raw = path.read_text(encoding="utf-8").strip()
        assert '"run_id":null' in raw
        rec = store.read_recent(days=2)[0]
        assert rec["run_id"] is None


class TestExecutionRoutePersistence:
    """Execution route fields survive JSONL round-trip."""

    def test_direct_yes_route_persisted(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()
        # The default _proposal helper doesn't set route fields → defaults
        # apply (display_side="", execution_market_id="", contract="yes",
        # route="direct_yes").  Override here for the test.
        prop_with_route = MakerProposal(
            **{**{f.name: getattr(prop, f.name) for f in prop.__dataclass_fields__.values()},
               "display_side": "Player A",
               "execution_market_id": "KXATPMATCH-A",
               "execution_contract_side": "yes",
               "execution_route": "direct_yes"}
        )
        store.append(prop_with_route, STATUS_PAPER_ACTIVE)
        records = store.read_recent(days=2)
        rec = records[0]
        assert rec["display_side"] == "Player A"
        assert rec["execution_market_id"] == "KXATPMATCH-A"
        assert rec["execution_contract_side"] == "yes"
        assert rec["execution_route"] == "direct_yes"

    def test_equivalent_no_route_persisted(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        prop = _proposal()
        prop_with_route = MakerProposal(
            **{**{f.name: getattr(prop, f.name) for f in prop.__dataclass_fields__.values()},
               "display_side": "Player A",
               "execution_market_id": "KXATPMATCH-B",
               "execution_contract_side": "no",
               "execution_route": "equivalent_no"}
        )
        store.append(prop_with_route, STATUS_PAPER_ACTIVE)
        rec = store.read_recent(days=2)[0]
        assert rec["display_side"] == "Player A"
        assert rec["execution_market_id"] == "KXATPMATCH-B"
        assert rec["execution_contract_side"] == "no"
        assert rec["execution_route"] == "equivalent_no"


class TestIter:
    def test_iter_day_yields_records(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        ts = time.time()
        for pid in ("a", "b", "c"):
            store.append(_proposal(proposal_id=pid, created_at=ts), STATUS_PAPER_ACTIVE)

        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        ids = [r["proposal_id"] for r in store.iter_day(day)]
        assert ids == ["a", "b", "c"]

    def test_iter_day_missing_yields_nothing(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        ids = list(store.iter_day(datetime(2099, 1, 1, tzinfo=timezone.utc).date()))
        assert ids == []
