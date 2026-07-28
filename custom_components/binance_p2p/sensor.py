"""Sensor platform for Binance P2P."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_AVAILABLE_AMOUNT,
    ATTR_LAST_UPDATED,
    ATTR_MAX_LIMIT,
    ATTR_MERCHANT,
    ATTR_MERCHANT_RATING,
    ATTR_MIN_LIMIT,
    ATTR_ORDER_COUNT,
    ATTR_PAYMENT_METHODS,
    CONF_ASSET,
    CONF_FIAT,
    CONF_TRADE_TYPE,
    DOMAIN,
)
from .coordinator import BinanceP2PCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Binance P2P sensor from a config entry."""
    coordinator: BinanceP2PCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BinanceP2PBestPriceSensor(coordinator, entry)])


class BinanceP2PBestPriceSensor(CoordinatorEntity[BinanceP2PCoordinator], SensorEntity):
    """Sensor exposing the best (top of book) Binance P2P offer."""

    _attr_has_entity_name = True
    _attr_name = "Best price"
    _attr_icon = "mdi:currency-usd"

    def __init__(self, coordinator: BinanceP2PCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

        asset = entry.data[CONF_ASSET]
        fiat = entry.data[CONF_FIAT]
        trade_type = entry.data[CONF_TRADE_TYPE]

        self._attr_unique_id = f"{entry.entry_id}_best_price"
        self._attr_native_unit_of_measurement = fiat
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Binance P2P {asset}/{fiat} {trade_type}",
            "manufacturer": "Binance (unofficial)",
            "model": "P2P best price",
        }

    @property
    def _best_offer(self) -> dict[str, Any] | None:
        offers = self.coordinator.data
        return offers[0] if offers else None

    @property
    def native_value(self) -> float | None:
        offer = self._best_offer
        return offer["price"] if offer else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        offer = self._best_offer
        if not offer:
            return {}

        return {
            ATTR_MERCHANT: offer["merchant"],
            ATTR_MIN_LIMIT: offer["min_limit"],
            ATTR_MAX_LIMIT: offer["max_limit"],
            ATTR_MERCHANT_RATING: offer["merchant_rating"],
            ATTR_ORDER_COUNT: offer["order_count"],
            ATTR_PAYMENT_METHODS: offer["payment_methods"],
            ATTR_AVAILABLE_AMOUNT: offer["available_amount"],
            ATTR_LAST_UPDATED: datetime.now(timezone.utc).isoformat(),
        }
