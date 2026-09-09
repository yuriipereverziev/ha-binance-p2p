"""Select platform for Binance P2P.

Exposes a single "Active bank" select entity per config entry, letting the
user pick one payment method at a time out of the ones already configured
during setup (Options -> Payment methods). Like the "Desired amount" number
entity, this is live, dashboard-adjustable runtime state - changing it
re-filters the already-cached offer list instantly, with no extra request
to Binance, and is persisted via the coordinator so it survives restarts.

Only created when the config entry actually has a pay_types list configured
(CONF_PAY_TYPES) - if the user never restricted payment methods, there is
nothing meaningful to narrow down to a single bank.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_ASSET, CONF_FIAT, CONF_TRADE_TYPE, DOMAIN
from .coordinator import BinanceP2PCoordinator

# Sentinel option meaning "no extra narrowing beyond the configured
# pay_types list" (coordinator.active_pay_type = None). Not a real Binance
# identifier, so it can never collide with an actual bank name.
ALL_BANKS_OPTION = "Все банки"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Binance P2P active-bank select entity."""
    coordinator: BinanceP2PCoordinator = hass.data[DOMAIN][entry.entry_id]
    if not coordinator.pay_types:
        return
    async_add_entities([BinanceP2PActiveBankSelect(coordinator, entry)])


class BinanceP2PActiveBankSelect(SelectEntity, RestoreEntity):
    """Live single-bank filter, narrowing the configured pay_types list."""

    _attr_has_entity_name = True
    _attr_translation_key = "active_bank"
    _attr_icon = "mdi:bank"

    def __init__(self, coordinator: BinanceP2PCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry

        asset = entry.data[CONF_ASSET]
        fiat = entry.data[CONF_FIAT]
        trade_type = entry.data[CONF_TRADE_TYPE]

        self._attr_unique_id = f"{entry.entry_id}_active_bank"
        self._attr_options = [ALL_BANKS_OPTION, *coordinator.pay_types]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Binance P2P {asset}/{fiat} {trade_type}",
            "manufacturer": "Binance (unofficial)",
            "model": "P2P best price",
        }

    async def async_added_to_hass(self) -> None:
        """Restore the last pick across HA restarts.

        Same reasoning as the desired-amount number entity: the
        coordinator's own persisted state (loaded before the first poll)
        is the primary source, this is just a safety net if the two
        somehow disagree.
        """
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (None, "unknown", "unavailable"):
            return
        restored = None if last_state.state == ALL_BANKS_OPTION else last_state.state
        if restored not in self._attr_options and restored is not None:
            return
        if restored != self._coordinator.active_pay_type:
            await self._coordinator.async_save_active_pay_type(restored)

    @property
    def available(self) -> bool:
        # Pure local/runtime state - stays usable even if the last Binance
        # poll failed, same as the desired-amount number entity.
        return True

    @property
    def current_option(self) -> str:
        return self._coordinator.active_pay_type or ALL_BANKS_OPTION

    async def async_select_option(self, option: str) -> None:
        """Update the filter and immediately refresh dependent entities.

        No new API call - just re-filters the offer list already cached
        in the coordinator.
        """
        value = None if option == ALL_BANKS_OPTION else option
        await self._coordinator.async_save_active_pay_type(value)