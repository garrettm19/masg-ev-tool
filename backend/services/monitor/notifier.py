"""
Notification delivery — Pushover provider with dry-run fallback.

Supports instant and digest modes, priority levels based on edge strength.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

_PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


@dataclass(frozen=True)
class AlertPayload:
    """Content for one notification."""
    title: str
    body: str
    url: str | None = None
    url_title: str | None = None
    priority: int = 0                  # -1=quiet, 0=normal, 1=high


class Notifier(Protocol):
    async def send(self, payload: AlertPayload) -> bool: ...
    async def send_batch(self, payloads: list[AlertPayload]) -> int: ...


class PushoverNotifier:
    """Send phone push notifications via Pushover."""

    def __init__(self, user_key: str, api_token: str):
        self._user_key = user_key
        self._api_token = api_token

    async def send(self, payload: AlertPayload) -> bool:
        if not self._user_key or not self._api_token:
            logger.warning("Pushover: missing credentials, skipping send")
            return False

        data = {
            "token": self._api_token,
            "user": self._user_key,
            "title": payload.title,
            "message": payload.body,
            "priority": payload.priority,
            "html": 1,
        }
        if payload.url:
            data["url"] = payload.url
        if payload.url_title:
            data["url_title"] = payload.url_title

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(_PUSHOVER_URL, data=data)
                resp.raise_for_status()
                logger.info("Pushover: sent '%s' (priority=%d)", payload.title, payload.priority)
                return True
        except Exception as exc:
            logger.error("Pushover: failed to send '%s': %s", payload.title, exc)
            return False

    async def send_batch(self, payloads: list[AlertPayload]) -> int:
        """Send multiple payloads, return count of successful sends."""
        sent = 0
        for p in payloads:
            if await self.send(p):
                sent += 1
        return sent


class DryRunNotifier:
    """Log alerts without actually sending them."""

    def __init__(self) -> None:
        self.sent: list[AlertPayload] = []

    async def send(self, payload: AlertPayload) -> bool:
        self.sent.append(payload)
        logger.info("[DRY RUN] Would send: %s — %s", payload.title, payload.body[:80])
        return True

    async def send_batch(self, payloads: list[AlertPayload]) -> int:
        for p in payloads:
            await self.send(p)
        return len(payloads)


# ---------------------------------------------------------------------------
# Deep links — open the iOS app directly
# ---------------------------------------------------------------------------

def _platform_deep_link(platform: str, web_url: str | None, event_slug: str | None) -> tuple[str | None, str]:
    """
    Return (url, url_title) using iOS app deep links where possible.

    Polymarket iOS: polymarket://event/{slug}  (falls back to web URL)
    Kalshi iOS:     kalshi://markets/{slug}     (falls back to web URL)

    If the app isn't installed, iOS opens the web URL as fallback.
    Pushover will show the url_title as a tappable button.
    """
    if platform == "polymarket":
        if event_slug:
            return f"https://polymarket.com/event/{event_slug}", "Open in Polymarket"
        if web_url:
            return web_url, "Open in Polymarket"
        return None, ""
    elif platform == "kalshi":
        if web_url:
            return web_url, "Open in Kalshi"
        return None, ""
    else:
        return web_url, "Open market" if web_url else ""


# ---------------------------------------------------------------------------
# Alert formatting
# ---------------------------------------------------------------------------

def format_instant_alert(
    event: str,
    platform: str,
    market_type: str,
    side: str,
    edge: float,
    p_true: float,
    pm_price: float,
    fd_confidence: str,
    url: str | None,
    event_slug: str | None = None,
    fd_odds: int = 0,
    kelly_pct: float = 0.0,
    high_priority_min_edge: float = 0.10,
) -> AlertPayload:
    """Build a concise, actionable push notification for a single opportunity."""
    ev_pct = f"{edge * 100:.1f}%"
    prob_pct = f"{p_true * 100:.0f}%"
    price_cents = f"{pm_price * 100:.0f}\u00a2"
    plat = "Polymarket" if platform == "polymarket" else "Kalshi" if platform == "kalshi" else platform
    mt = {"h2h": "H2H", "totals": "Totals", "handicap": "Handicap"}.get(market_type, market_type.upper())
    odds_str = f"+{fd_odds}" if fd_odds > 0 else str(fd_odds)

    title = f"\u26a1 +{ev_pct} EV \u2014 {side}"

    lines = [
        f"{event}",
        f"{plat} {mt} \u00b7 Buy at {price_cents}",
        f"True prob {prob_pct} \u00b7 FD {odds_str} \u00b7 {fd_confidence}",
    ]
    if kelly_pct > 0:
        lines.append(f"Kelly: {kelly_pct:.1f}%")

    body = "\n".join(lines)
    priority = 1 if edge >= high_priority_min_edge else 0
    deep_url, deep_title = _platform_deep_link(platform, url, event_slug)

    return AlertPayload(
        title=title,
        body=body,
        url=deep_url,
        url_title=deep_title if deep_url else None,
        priority=priority,
    )


def format_digest_alert(opportunities: list[dict]) -> AlertPayload:
    """Build a batched digest notification summarizing multiple opportunities."""
    count = len(opportunities)
    lines = []
    for o in opportunities[:8]:
        ev_pct = f"{o['edge'] * 100:.1f}%"
        plat = "PM" if o["platform"] == "polymarket" else "K"
        lines.append(f"+{ev_pct} {o['side'][:18]} ({plat})")

    title = f"{count} new opportunit{'y' if count == 1 else 'ies'}"
    body = "\n".join(lines)
    if count > 8:
        body += f"\n… and {count - 8} more"

    return AlertPayload(title=title, body=body, priority=0)
