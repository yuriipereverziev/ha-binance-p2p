"""DataUpdateCoordinator for Binance P2P."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BinanceP2PClient, BinanceP2PError
from .const import (
    CONF_ASSET,
    CONF_CARD_TYPES,
    CONF_DESIRED_AMOUNT,
    CONF_FIAT,
    CONF_PAY_TYPES,
    CONF_SCAN_INTERVAL,
    CONF_TRADE_TYPE,
    DEFAULT_DESIRED_AMOUNT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

HISTORY_STORAGE_VERSION = 1
HISTORY_WINDOW = timedelta(hours=24)
STATE_STORAGE_VERSION = 1


class BinanceP2PCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinates polling of the Binance P2P offer list for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        self.pay_types = entry.options.get(
            CONF_PAY_TYPES, entry.data.get(CONF_PAY_TYPES, [])
        )
        self.card_types = entry.options.get(
            CONF_CARD_TYPES, entry.data.get(CONF_CARD_TYPES, [])
        )

        session = async_get_clientsession(hass)
        self.client = BinanceP2PClient(
            session=session,
            asset=entry.data[CONF_ASSET],
            fiat=entry.data[CONF_FIAT],
            trade_type=entry.data[CONF_TRADE_TYPE],
            pay_types=self.pay_types,
            card_types=self.card_types,
        )

        # Desired transaction amount, used by entities to pick the best
        # offer whose min/max limit actually covers this amount. This is
        # changed live via the "Desired amount" number entity, not via the
        # config/options flow - it's runtime state, not a static setting.
        # 0 means "no filter", i.e. just show the plain top-of-book offer.
        self.desired_amount: float = entry.data.get(
            CONF_DESIRED_AMOUNT, DEFAULT_DESIRED_AMOUNT
        )

        # Rolling 24h history of the top-of-book offer at each poll, used
        # for the "top offers (24h)" sensor. Persisted to disk (one file
        # per config entry) so a HA restart doesn't wipe the day's data -
        # loaded via async_load_persisted_state(), which __init__.py awaits
        # before the first refresh.
        self._history_store: Store[list[dict[str, Any]]] = Store(
            hass, HISTORY_STORAGE_VERSION, f"{DOMAIN}_history_{entry.entry_id}"
        )
        self._history: list[dict[str, Any]] = []

        # desired_amount is also persisted here (separately from the number
        # entity's own RestoreEntity state). Reason: the coordinator's
        # first refresh runs during __init__.py's async_setup_entry, before
        # platforms (and the number entity's async_added_to_hass restore)
        # are ever set up - so relying on the entity to restore the value
        # meant every HA restart recorded one history snapshot with
        # desired_amount back at its 0/no-filter default, polluting the
        # 24h top-offers list with offers that don't actually match the
        # user's amount. Loading it here first closes that gap.
        self._state_store: Store[dict[str, Any]] = Store(
            hass, STATE_STORAGE_VERSION, f"{DOMAIN}_state_{entry.entry_id}"
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def async_load_persisted_state(self) -> None:
        """Load persisted history and desired_amount. Call before first refresh."""
        stored_history = await self._history_store.async_load()
        self._history = stored_history or []
        self._prune_history()

        stored_state = await self._state_store.async_load()
        if stored_state and "desired_amount" in stored_state:
            self.desired_amount = stored_state["desired_amount"]

    async def async_save_desired_amount(self, value: float) -> None:
        """Update desired_amount, persist it, and refresh dependent entities."""
        self.desired_amount = value
        await self._state_store.async_save({"desired_amount": value})
        self.async_update_listeners()

    def _prune_history(self) -> None:
        cutoff = datetime.now(timezone.utc) - HISTORY_WINDOW
        self._history = [
            snap
            for snap in self._history
            if datetime.fromisoformat(snap["timestamp"]) >= cutoff
        ]

    def _record_snapshot(self, best: dict[str, Any]) -> None:
        self._history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "price": best["price"],
                "merchant": best["merchant"],
                "merchant_rating": best["merchant_rating"],
                "order_count": best["order_count"],
                "min_limit": best["min_limit"],
                "max_limit": best["max_limit"],
            }
        )
        self._prune_history()

    def top_offers(self, n: int = 3) -> list[dict[str, Any]]:
        """Return the n best snapshots from the last 24h.

        "Best" follows the same direction as the live offer sort: highest
        price for SELL (we're selling, want more), lowest for BUY (we're
        buying, want less).
        """
        reverse = self.entry.data[CONF_TRADE_TYPE] == "SELL"
        return sorted(
            self._history, key=lambda s: s["price"], reverse=reverse
        )[:n]

    @staticmethod
    def _offer_covers_amount(offer: dict[str, Any], amount: float) -> bool:
        """Check both the advertised limits and the merchant's real surplus.

        An offer's min/max limit alone isn't enough: a merchant may have a
        high max_limit but very little crypto actually left to sell/buy
        (available_amount). Without this check we could point the user at
        an offer that looks big enough on paper but can't actually fill
        their desired fiat amount.
        """
        if not (offer["min_limit"] <= amount <= offer["max_limit"]):
            return False
        if not offer["price"]:
            return False
        required_qty = amount / offer["price"]
        return required_qty <= offer["available_amount"]

    def _pick_best(self, offers: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Pick the best offer from an already-filtered list, honoring
        ``desired_amount`` (0 = no amount filter, just top-of-book).

        Shared by best_offer() (against the cached self.data) and history
        recording (against the freshly fetched list, before self.data is
        updated) so both apply the exact same amount/liquidity logic.
        """
        if not offers:
            return None
        amount = self.desired_amount
        if not amount:
            return offers[0]
        for offer in offers:
            if self._offer_covers_amount(offer, amount):
                return offer
        return None

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            offers = await self.client.async_fetch_offers()
        except BinanceP2PError as err:
            raise UpdateFailed(str(err)) from err

        if not offers:
            raise UpdateFailed("Binance P2P returned no offers for this pair")

        # Record whatever the user would actually see right now - already
        # respects pay_types/card_types (applied inside async_fetch_offers)
        # and desired_amount (applied here), not just the raw top-of-book.
        best = self._pick_best(offers)
        if best is not None:
            self._record_snapshot(best)
            await self._history_store.async_save(self._history)

        return offers

    def best_offer(self) -> dict[str, Any] | None:
        """Return the best offer that can cover ``desired_amount``.

        If ``desired_amount`` is 0 (no filter set), just returns the plain
        top-of-book offer. Filtering happens against the already-cached
        offer list, so changing the amount never triggers a new API call.
        """
        return self._pick_best(self.data or [])

    def matching_offers_count(self) -> int:
        """Count offers that can actually cover the current desired amount."""
        offers = self.data or []
        amount = self.desired_amount
        if not amount:
            return len(offers)
        return sum(1 for o in offers if self._offer_covers_amount(o, amount))
