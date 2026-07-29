"""DataUpdateCoordinator for Binance P2P."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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


class BinanceP2PCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinates polling of the Binance P2P offer list for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        session = async_get_clientsession(hass)
        self.client = BinanceP2PClient(
            session=session,
            asset=entry.data[CONF_ASSET],
            fiat=entry.data[CONF_FIAT],
            trade_type=entry.data[CONF_TRADE_TYPE],
            pay_types=entry.data.get(CONF_PAY_TYPES, []),
            card_types=entry.data.get(CONF_CARD_TYPES, []),
        )

        # Desired transaction amount, used by entities to pick the best
        # offer whose min/max limit actually covers this amount. This is
        # changed live via the "Desired amount" number entity, not via the
        # config/options flow - it's runtime state, not a static setting.
        # 0 means "no filter", i.e. just show the plain top-of-book offer.
        self.desired_amount: float = entry.data.get(
            CONF_DESIRED_AMOUNT, DEFAULT_DESIRED_AMOUNT
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            offers = await self.client.async_fetch_offers()
        except BinanceP2PError as err:
            raise UpdateFailed(str(err)) from err

        if not offers:
            raise UpdateFailed("Binance P2P returned no offers for this pair")

        return offers

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

    def best_offer(self) -> dict[str, Any] | None:
        """Return the best offer that can cover ``desired_amount``.

        If ``desired_amount`` is 0 (no filter set), just returns the plain
        top-of-book offer. Filtering happens against the already-cached
        offer list, so changing the amount never triggers a new API call.
        """
        offers = self.data
        if not offers:
            return None

        amount = self.desired_amount
        if not amount:
            return offers[0]

        for offer in offers:
            if self._offer_covers_amount(offer, amount):
                return offer
        return None

    def matching_offers_count(self) -> int:
        """Count offers that can actually cover the current desired amount."""
        offers = self.data or []
        amount = self.desired_amount
        if not amount:
            return len(offers)
        return sum(1 for o in offers if self._offer_covers_amount(o, amount))
