"""Config flow for Binance P2P."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BinanceP2PClient, BinanceP2PError
from .const import (
    CONF_ASSET,
    CONF_FIAT,
    CONF_PAY_TYPES,
    CONF_SCAN_INTERVAL,
    CONF_TRADE_TYPE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRADE_TYPE,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    TRADE_TYPES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ASSET, default="USDT"): str,
        vol.Required(CONF_FIAT, default="UAH"): str,
        vol.Required(CONF_TRADE_TYPE, default=DEFAULT_TRADE_TYPE): vol.In(TRADE_TYPES),
        vol.Optional(CONF_PAY_TYPES, default=""): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
        ),
    }
)


def _parse_pay_types(raw: str) -> list[str]:
    """Turn a comma-separated pay-type string into a clean list."""
    return [p.strip() for p in raw.split(",") if p.strip()]


class BinanceP2PConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Binance P2P."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            asset = user_input[CONF_ASSET].strip().upper()
            fiat = user_input[CONF_FIAT].strip().upper()
            trade_type = user_input[CONF_TRADE_TYPE]
            pay_types = _parse_pay_types(user_input.get(CONF_PAY_TYPES, ""))
            scan_interval = user_input[CONF_SCAN_INTERVAL]

            unique_id = f"{asset}_{fiat}_{trade_type}".lower()
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = BinanceP2PClient(
                session=session,
                asset=asset,
                fiat=fiat,
                trade_type=trade_type,
                pay_types=pay_types,
            )

            try:
                offers = await client.async_fetch_offers()
            except BinanceP2PError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Binance P2P setup")
                errors["base"] = "unknown"
            else:
                if not offers:
                    errors["base"] = "no_offers"
                else:
                    return self.async_create_entry(
                        title=f"Binance P2P {asset}/{fiat} {trade_type}",
                        data={
                            CONF_ASSET: asset,
                            CONF_FIAT: fiat,
                            CONF_TRADE_TYPE: trade_type,
                            CONF_PAY_TYPES: pay_types,
                            CONF_SCAN_INTERVAL: scan_interval,
                        },
                    )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> BinanceP2POptionsFlow:
        return BinanceP2POptionsFlow(entry)


class BinanceP2POptionsFlow(OptionsFlow):
    """Allow changing the scan interval after setup, without a reconfigure."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._entry.options.get(
            CONF_SCAN_INTERVAL,
            self._entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
