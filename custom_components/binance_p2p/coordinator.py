"""DataUpdateCoordinator for Binance P2P."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)

from .api import BinanceP2PClient, BinanceP2PError
from .const import (
    CONF_ALERT_PRICE_FROM,
    CONF_ALERT_PRICE_TO,
    CONF_ASSET,
    CONF_CARD_TYPES,
    CONF_DESIRED_AMOUNT,
    CONF_FIAT,
    CONF_PAY_TYPES,
    CONF_SCAN_INTERVAL,
    CONF_TRADE_TYPE,
    DEFAULT_ALERT_PRICE_FROM,
    DEFAULT_ALERT_PRICE_TO,
    DEFAULT_DESIRED_AMOUNT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

HISTORY_STORAGE_VERSION = 1
HISTORY_WINDOW = timedelta(hours=24)
STATE_STORAGE_VERSION = 1


class BinanceP2PCoordinator(TimestampDataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinates polling of the Binance P2P offer list for one config entry.

    Subclasses TimestampDataUpdateCoordinator (not the plain
    DataUpdateCoordinator) specifically so ``last_update_success_time`` is
    tracked for us and can be read from the sensor - see sensor.py's
    "next update" countdown attributes.
    """

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

        # Live single-bank filter, changed via the "Active bank" select
        # entity (select.py) - narrows the already-configured pay_types
        # list down to one bank at a time, applied client-side against the
        # cached offer list (see _offer_matches). None = no extra
        # narrowing, i.e. all of the configured pay_types still apply.
        self.active_pay_type: str | None = None

        # Desired transaction amount, used by entities to pick the best
        # offer whose min/max limit actually covers this amount. This is
        # changed live via the "Desired amount" number entity, not via the
        # config/options flow - it's runtime state, not a static setting.
        # 0 means "no filter", i.e. just show the plain top-of-book offer.
        self.desired_amount: float = entry.data.get(
            CONF_DESIRED_AMOUNT, DEFAULT_DESIRED_AMOUNT
        )

        # Live price-alert range, adjustable from the dashboard via the
        # "Alert price: from/to" number entities (number.py) - same
        # live/dashboard-adjustable pattern as desired_amount and
        # active_pay_type above. Changing it re-filters already-cached
        # data and updates the alert_price_from/alert_price_to
        # attributes on the best-price sensor instantly, no new Binance
        # request.
        #
        # Seeded here from the config/options flow's alert_price_from/
        # alert_price_to fields (CONF_ALERT_PRICE_FROM/TO) - that's still
        # how you set the *initial* range. But once a value has been
        # saved live (persisted below in _async_save_runtime_state, same
        # store as desired_amount/active_pay_type), that persisted value
        # wins on every subsequent load, same as those two. In practice
        # that means: after you've adjusted the range from the dashboard
        # even once, editing it again via the integration's Options
        # screen won't visibly change anything until you also touch the
        # dashboard sliders - Options is just the starting point, the
        # dashboard is the day-to-day control.
        self.alert_price_from: float = float(
            entry.options.get(
                CONF_ALERT_PRICE_FROM,
                entry.data.get(CONF_ALERT_PRICE_FROM, DEFAULT_ALERT_PRICE_FROM),
            )
        )
        self.alert_price_to: float = float(
            entry.options.get(
                CONF_ALERT_PRICE_TO,
                entry.data.get(CONF_ALERT_PRICE_TO, DEFAULT_ALERT_PRICE_TO),
            )
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

        # desired_amount (and friends) is also persisted here (separately
        # from each number/select entity's own RestoreEntity state).
        # Reason: the coordinator's first refresh runs during
        # __init__.py's async_setup_entry, before platforms (and each
        # entity's async_added_to_hass restore) are ever set up - so
        # relying on the entity to restore the value meant every HA
        # restart recorded one history snapshot with these back at their
        # config-default values, polluting the 24h top-offers list with
        # offers that don't actually match the user's current filters.
        # Loading it here first closes that gap.
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
        """Load persisted history and live filters. Call before first refresh."""
        stored_history = await self._history_store.async_load()
        self._history = stored_history or []
        self._prune_history()

        stored_state = await self._state_store.async_load()
        if stored_state:
            if "desired_amount" in stored_state:
                self.desired_amount = stored_state["desired_amount"]
            if "active_pay_type" in stored_state:
                self.active_pay_type = stored_state["active_pay_type"]
            if "alert_price_from" in stored_state:
                self.alert_price_from = stored_state["alert_price_from"]
            if "alert_price_to" in stored_state:
                self.alert_price_to = stored_state["alert_price_to"]

    async def _async_save_runtime_state(self) -> None:
        """Persist all live filters together (a plain overwrite of one key
        would otherwise wipe the others - the store holds a single dict)."""
        await self._state_store.async_save(
            {
                "desired_amount": self.desired_amount,
                "active_pay_type": self.active_pay_type,
                "alert_price_from": self.alert_price_from,
                "alert_price_to": self.alert_price_to,
            }
        )

    async def async_save_desired_amount(self, value: float) -> None:
        """Update desired_amount, persist it, and refresh dependent entities."""
        self.desired_amount = value
        await self._async_save_runtime_state()
        self.async_update_listeners()

    async def async_save_active_pay_type(self, value: str | None) -> None:
        """Update the live single-bank filter, persist it, and refresh
        dependent entities. No new Binance request - just re-filters the
        already-cached offer list, same as async_save_desired_amount."""
        self.active_pay_type = value
        await self._async_save_runtime_state()
        self.async_update_listeners()

    async def async_save_alert_price_from(self, value: float) -> None:
        """Update the live lower bound of the alert range, persist it, and
        refresh dependent entities (the best-price sensor's
        alert_price_from attribute, and any automation reading it) - same
        no-extra-request pattern as async_save_desired_amount."""
        self.alert_price_from = value
        await self._async_save_runtime_state()
        self.async_update_listeners()

    async def async_save_alert_price_to(self, value: float) -> None:
        """Same as async_save_alert_price_from, for the upper bound."""
        self.alert_price_to = value
        await self._async_save_runtime_state()
        self.async_update_listeners()

    def _prune_history(self) -> None:
        """Drop anything older than the window - and anything malformed.

        Defensive against entries that don't match the expected shape
        (e.g. a partially-written save, or a leftover from manual editing
        of the storage file): a single bad entry used to raise KeyError
        here and take down the entire integration's setup, since this
        runs before the coordinator's first refresh.
        """
        cutoff = datetime.now(timezone.utc) - HISTORY_WINDOW
        cleaned: list[dict[str, Any]] = []
        for snap in self._history:
            ts = snap.get("timestamp") if isinstance(snap, dict) else None
            if not ts:
                continue
            try:
                parsed = datetime.fromisoformat(ts)
            except (TypeError, ValueError):
                continue
            if parsed >= cutoff:
                cleaned.append(snap)
        self._history = cleaned

    def _record_snapshot(self, best: dict[str, Any]) -> None:
        self._history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "price": best["price"],
                "merchant": best["merchant"],
                "adv_no": best.get("adv_no"),
                "merchant_rating": best["merchant_rating"],
                "order_count": best["order_count"],
                "min_limit": best["min_limit"],
                "max_limit": best["max_limit"],
                "payment_method_ids": best.get("payment_method_ids", []),
            }
        )
        self._prune_history()

    def _snapshot_matches_current_filters(self, snap: dict[str, Any]) -> bool:
        """Re-check a stored history snapshot against the filters as they
        are configured *right now* (not as they were when it was recorded).

        This is what makes top_offers() live: changing the alert price
        range or desired amount immediately hides now-stale entries from
        the displayed top-3, instead of waiting for them to age out of the
        24h window on their own.

        Note: snapshots don't store available_amount, so the amount check
        here is limited to min/max limit (unlike the live liquidity check
        in _offer_covers_amount) - good enough to hide obviously
        non-matching entries without needing to re-fetch anything.
        """
        price = snap.get("price")
        if price is None:
            return False
        lo = self.alert_price_from
        hi = self.alert_price_to
        if lo and price < lo:
            return False
        if hi and price > hi:
            return False

        amount = self.desired_amount
        if amount:
            min_l = snap.get("min_limit")
            max_l = snap.get("max_limit")
            if min_l is None or max_l is None:
                return False
            if not (min_l <= amount <= max_l):
                return False

        if self.active_pay_type:
            # Snapshots recorded before this field existed have no
            # payment_method_ids - treat those as non-matching once a bank
            # filter is active, rather than silently ignoring the filter.
            if self.active_pay_type not in snap.get("payment_method_ids", []):
                return False
        return True

    def top_offers(self, n: int = 3) -> list[dict[str, Any]]:
        """Return the n best snapshots from the last 24h that still match
        the *current* filters (price range, amount) - re-checked here, not
        just at the moment each snapshot was recorded. Otherwise changing
        the alert range or desired amount would leave old, now-non-matching
        entries lingering in the displayed top-3 until they age out of the
        24h window on their own.

        "Best" follows the same direction as the live offer sort: highest
        price for SELL (we're selling, want more), lowest for BUY (we're
        buying, want less).
        """
        matching = [
            s for s in self._history if self._snapshot_matches_current_filters(s)
        ]
        reverse = self.entry.data[CONF_TRADE_TYPE] == "SELL"
        return sorted(matching, key=lambda s: s["price"], reverse=reverse)[:n]

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

    def _offer_in_price_range(self, offer: dict[str, Any]) -> bool:
        """True if offer price is inside the configured alert range.

        0 on either side means "no bound on that side". Both 0 = no price
        filter at all (same as before this filter existed).
        """
        price = offer.get("price")
        if not price:
            return False
        lo = self.alert_price_from
        hi = self.alert_price_to
        if lo and price < lo:
            return False
        if hi and price > hi:
            return False
        return True

    def _offer_matches(self, offer: dict[str, Any]) -> bool:
        """Apply the amount filter, the price-range filter, and (if set)
        the live single-bank filter."""
        if not self._offer_in_price_range(offer):
            return False
        amount = self.desired_amount
        if amount and not self._offer_covers_amount(offer, amount):
            return False
        if (
            self.active_pay_type
            and self.active_pay_type not in offer["payment_method_ids"]
        ):
            return False
        return True

    def _pick_best(self, offers: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Pick the best offer honoring desired_amount and alert price range.

        Shared by best_offer() (against the cached self.data) and history
        recording (against the freshly fetched list) so both apply the
        exact same filters the user sees on the dashboard.
        """
        if not offers:
            return None
        for offer in offers:
            if self._offer_matches(offer):
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
        # and desired_amount + alert price range (applied here).
        best = self._pick_best(offers)
        if best is not None:
            self._record_snapshot(best)
            await self._history_store.async_save(self._history)

        return offers

    def best_offer(self) -> dict[str, Any] | None:
        """Return the best offer matching desired_amount and price range.

        Filtering happens against the already-cached offer list, so
        changing the amount never triggers a new API call. Price range
        comes from config/options and is applied on every read.
        """
        return self._pick_best(self.data or [])

    def matching_offers_count(self) -> int:
        """Count offers that match both amount and price-range filters."""
        offers = self.data or []
        return sum(1 for o in offers if self._offer_matches(o))