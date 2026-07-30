"""Number platform for Binance P2P.

Exposes a single "Desired amount" number entity per config entry. Binance
P2P offers each carry a min/max transaction limit, so the "best price"
depends on how much you actually want to trade. Rather than fixing this at
setup time (which would mean re-opening Settings every time the amount
changes), it's exposed as a live, dashboard-adjustable `number` entity:
changing it re-filters the already-cached offer list instantly, with no
extra request to Binance.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_ASSET,
    CONF_FIAT,
    CONF_TRADE_TYPE,
    DOMAIN,
    NUMBER_MAX_AMOUNT,
    NUMBER_STEP_AMOUNT,
)
from .coordinator import BinanceP2PCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Binance P2P desired-amount number entity."""
    coordinator: BinanceP2PCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BinanceP2PDesiredAmountNumber(coordinator, entry)])


class BinanceP2PDesiredAmountNumber(NumberEntity, RestoreEntity):
    """Desired transaction amount, used to filter the best-price sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "desired_amount"
    _attr_icon = "mdi:cash-marker"
    _attr_native_min_value = 0
    _attr_native_max_value = NUMBER_MAX_AMOUNT
    _attr_native_step = NUMBER_STEP_AMOUNT
    # AUTO lets the frontend/theme decide slider vs. box based on the
    # min/max/step range, rather than forcing one or the other.
    _attr_mode = NumberMode.AUTO

    def __init__(self, coordinator: BinanceP2PCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry

        asset = entry.data[CONF_ASSET]
        fiat = entry.data[CONF_FIAT]
        trade_type = entry.data[CONF_TRADE_TYPE]

        self._attr_unique_id = f"{entry.entry_id}_desired_amount"
        self._attr_native_unit_of_measurement = fiat
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Binance P2P {asset}/{fiat} {trade_type}",
            "manufacturer": "Binance (unofficial)",
            "model": "P2P best price",
        }

    async def async_added_to_hass(self) -> None:
        """Restore the last value across HA restarts (0 = no filter).

        As of the coordinator's own desired_amount persistence (see
        coordinator.py), this mainly matters as a one-time migration path
        for entries that already had a value saved via RestoreEntity from
        before that existed - on every restart after that, the coordinator
        loads its own persisted value before this even runs. Still safe to
        keep: if the two ever disagree, use the entity's value.
        """
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            None,
            "unknown",
            "unavailable",
        ):
            try:
                restored = float(last_state.state)
            except ValueError:
                return
            if restored != self._coordinator.desired_amount:
                await self._coordinator.async_save_desired_amount(restored)

    @property
    def available(self) -> bool:
        # This entity is pure local/runtime state - it doesn't depend on the
        # last Binance poll having succeeded, so it stays usable even if the
        # price sensor is temporarily unavailable.
        return True

    @property
    def native_value(self) -> float:
        return self._coordinator.desired_amount

    async def async_set_native_value(self, value: float) -> None:
        """Update the filter and immediately refresh dependent entities.

        No new API call is made - this just re-filters the offer list
        that's already cached in the coordinator. Persisted via the
        coordinator's own storage (see coordinator.py) so it's available
        before the next HA restart's first poll, not just restored here.
        """
        await self._coordinator.async_save_desired_amount(value)
