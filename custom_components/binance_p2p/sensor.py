"""Sensor platform for Binance P2P."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ACTIVE_CARD_TYPES,
    ATTR_ACTIVE_PAY_TYPES,
    ATTR_ALERT_PRICE_FROM,
    ATTR_ALERT_PRICE_TO,
    ATTR_AVAILABLE_AMOUNT,
    ATTR_DESIRED_AMOUNT,
    ATTR_LAST_UPDATED,
    ATTR_MATCHING_OFFERS,
    ATTR_MAX_LIMIT,
    ATTR_MERCHANT,
    ATTR_MERCHANT_RATING,
    ATTR_MIN_LIMIT,
    ATTR_ORDER_COUNT,
    ATTR_PAYMENT_METHOD_IDS,
    ATTR_PAYMENT_METHODS,
    ATTR_SCAN_INTERVAL,
    ATTR_TOP_OFFERS_24H,
    CONF_ALERT_PRICE_FROM,
    CONF_ALERT_PRICE_TO,
    CONF_ASSET,
    CONF_FIAT,
    CONF_SCAN_INTERVAL,
    CONF_TRADE_TYPE,
    DEFAULT_ALERT_PRICE_FROM,
    DEFAULT_ALERT_PRICE_TO,
    DEFAULT_SCAN_INTERVAL,
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
    async_add_entities(
        [
            BinanceP2PBestPriceSensor(coordinator, entry),
            BinanceP2PTopOffersSensor(coordinator, entry),
        ]
    )


class BinanceP2PBestPriceSensor(CoordinatorEntity[BinanceP2PCoordinator], SensorEntity):
    """Sensor exposing the best (top of book) Binance P2P offer."""

    _attr_has_entity_name = True
    _attr_translation_key = "best_price"
    _attr_icon = "mdi:currency-usd"
    # Note: HA only allows state_class="total" together with device_class
    # MONETARY, and that doesn't semantically fit a fluctuating spot price
    # (it's meant for cumulative totals like "cost today"). So we set the
    # device class for currency formatting only, and leave state_class unset
    # (no long-term statistics/energy-dashboard integration, just History).
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

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
        return self.coordinator.best_offer()

    @property
    def native_value(self) -> float | None:
        offer = self._best_offer
        return offer["price"] if offer else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        offer = self._best_offer
        # Prefer the coordinator's actual last successful poll time so the
        # countdown in the dashboard is accurate; fall back to "now" only
        # if the coordinator has never reported a success timestamp yet.
        last_ts = self.coordinator.last_update_success_timestamp
        if last_ts is not None:
            last_updated = last_ts.isoformat()
        else:
            last_updated = datetime.now(timezone.utc).isoformat()

        scan_interval = (
            int(self.coordinator.update_interval.total_seconds())
            if self.coordinator.update_interval
            else self._entry.options.get(
                CONF_SCAN_INTERVAL,
                self._entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )

        attrs: dict[str, Any] = {
            ATTR_DESIRED_AMOUNT: self.coordinator.desired_amount,
            ATTR_MATCHING_OFFERS: self.coordinator.matching_offers_count(),
            ATTR_ACTIVE_PAY_TYPES: self.coordinator.pay_types,
            ATTR_ACTIVE_CARD_TYPES: self.coordinator.card_types,
            ATTR_SCAN_INTERVAL: scan_interval,
            ATTR_LAST_UPDATED: last_updated,
            # Price-alert range chosen at setup (editable later via
            # Options). 0 on either side means "no bound there" - exposed
            # as attributes so automations can reference the user's
            # configured range instead of hardcoding numbers in the
            # automation YAML.
            ATTR_ALERT_PRICE_FROM: self.coordinator.alert_price_from,
            ATTR_ALERT_PRICE_TO: self.coordinator.alert_price_to,
        }
        if not offer:
            return attrs

        attrs.update(
            {
                ATTR_MERCHANT: offer["merchant"],
                ATTR_MIN_LIMIT: offer["min_limit"],
                ATTR_MAX_LIMIT: offer["max_limit"],
                ATTR_MERCHANT_RATING: offer["merchant_rating"],
                ATTR_ORDER_COUNT: offer["order_count"],
                ATTR_PAYMENT_METHODS: offer["payment_methods"],
                ATTR_PAYMENT_METHOD_IDS: offer["payment_method_ids"],
                ATTR_AVAILABLE_AMOUNT: offer["available_amount"],
            }
        )
        return attrs


class BinanceP2PTopOffersSensor(CoordinatorEntity[BinanceP2PCoordinator], SensorEntity):
    """Sensor exposing the best price seen in the last 24h and the top 3.

    The state is the best single price observed (so it works with
    numeric_state automations/history graphs); the full top-3 - with
    merchant, rating, limits and when it was seen - is in the
    ``top_offers`` attribute.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "top_offers_24h"
    _attr_icon = "mdi:trophy-outline"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BinanceP2PCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

        asset = entry.data[CONF_ASSET]
        fiat = entry.data[CONF_FIAT]
        trade_type = entry.data[CONF_TRADE_TYPE]

        self._attr_unique_id = f"{entry.entry_id}_top_offers_24h"
        self._attr_native_unit_of_measurement = fiat
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Binance P2P {asset}/{fiat} {trade_type}",
            "manufacturer": "Binance (unofficial)",
            "model": "P2P best price",
        }

    @property
    def _top3(self) -> list[dict[str, Any]]:
        return self.coordinator.top_offers(3)

    @property
    def native_value(self) -> float | None:
        top = self._top3
        return top[0]["price"] if top else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_TOP_OFFERS_24H: self._top3}
