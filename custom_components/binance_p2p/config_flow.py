"""Config flow for Binance P2P."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BinanceP2PClient, BinanceP2PError, async_fetch_payment_methods
from .const import (
    CONF_ASSET,
    CONF_CARD_TYPES,
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
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
        ),
    }
)


class BinanceP2PConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Binance P2P."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._pay_type_options: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            asset = user_input[CONF_ASSET].strip().upper()
            fiat = user_input[CONF_FIAT].strip().upper()
            trade_type = user_input[CONF_TRADE_TYPE]
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
                pay_types=[],
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
                    self._data = {
                        CONF_ASSET: asset,
                        CONF_FIAT: fiat,
                        CONF_TRADE_TYPE: trade_type,
                        CONF_SCAN_INTERVAL: scan_interval,
                    }

                    # Best-effort: fetch Binance's own list of payment
                    # method identifiers for this fiat, so the next step
                    # can offer a validated multi-select instead of a
                    # free-text field. If this fails, just skip the
                    # payment-method step entirely (no filter = any).
                    try:
                        self._pay_type_options = await async_fetch_payment_methods(
                            session, fiat
                        )
                    except BinanceP2PError:
                        _LOGGER.warning(
                            "Could not fetch payment methods for %s; "
                            "continuing without a payment method filter",
                            fiat,
                        )
                        self._pay_type_options = []

                    if self._pay_type_options:
                        return await self.async_step_payment_methods()

                    self._data[CONF_PAY_TYPES] = []
                    self._data[CONF_CARD_TYPES] = []
                    return self.async_create_entry(
                        title=f"Binance P2P {asset}/{fiat} {trade_type}",
                        data=self._data,
                    )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_payment_methods(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Let the user pick payment methods from Binance's real list.

        Two independent, optional multi-selects, both left empty by default
        (= no filter, same as before):

        - pay_types: general accepted payment methods
        - card_types: a second, ANDed condition - the offer must ALSO
          support at least one of these specific banks/cards for crediting
          funds. Kept as a separate field rather than folded into pay_types
          because the two are combined with AND, not OR - see
          BinanceP2PClient.async_fetch_offers().
        """
        if user_input is not None:
            self._data[CONF_PAY_TYPES] = user_input.get(CONF_PAY_TYPES, [])
            self._data[CONF_CARD_TYPES] = user_input.get(CONF_CARD_TYPES, [])
            asset = self._data[CONF_ASSET]
            fiat = self._data[CONF_FIAT]
            trade_type = self._data[CONF_TRADE_TYPE]
            return self.async_create_entry(
                title=f"Binance P2P {asset}/{fiat} {trade_type}",
                data=self._data,
            )

        options = [
            selector.SelectOptionDict(value=m["identifier"], label=m["name"])
            for m in self._pay_type_options
        ]
        schema = vol.Schema(
            {
                vol.Optional(CONF_PAY_TYPES, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_CARD_TYPES, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="payment_methods", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> BinanceP2POptionsFlow:
        return BinanceP2POptionsFlow(entry)


class BinanceP2POptionsFlow(OptionsFlow):
    """Allow changing scan interval and payment/card filters after setup."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._pay_type_options: list[dict[str, str]] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._entry.options.get(
            CONF_SCAN_INTERVAL,
            self._entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        # Best-effort: fetch the live payment-method list so the user picks
        # from validated options here too. If it fails, fall back to just
        # showing the interval field (same degrade-gracefully behavior as
        # the initial config flow).
        session = async_get_clientsession(self.hass)
        try:
            self._pay_type_options = await async_fetch_payment_methods(
                session, self._entry.data[CONF_FIAT]
            )
        except BinanceP2PError:
            _LOGGER.warning(
                "Could not fetch payment methods for options flow; "
                "showing only the update interval"
            )
            self._pay_type_options = []

        current_pay_types = self._entry.options.get(
            CONF_PAY_TYPES, self._entry.data.get(CONF_PAY_TYPES, [])
        )
        current_card_types = self._entry.options.get(
            CONF_CARD_TYPES, self._entry.data.get(CONF_CARD_TYPES, [])
        )

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
            ),
        }

        if self._pay_type_options:
            options = [
                selector.SelectOptionDict(value=m["identifier"], label=m["name"])
                for m in self._pay_type_options
            ]
            schema_dict[
                vol.Optional(CONF_PAY_TYPES, default=current_pay_types)
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            schema_dict[
                vol.Optional(CONF_CARD_TYPES, default=current_card_types)
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
