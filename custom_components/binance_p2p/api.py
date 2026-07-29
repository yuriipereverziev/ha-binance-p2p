"""Thin async client for the public Binance P2P search endpoint."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import BINANCE_P2P_TRADE_METHODS_URL, BINANCE_P2P_URL, DEFAULT_ROWS

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# Binance/Cloudflare tends to challenge or block requests that look like a
# bare aiohttp client, so we present ourselves as a normal browser request.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class BinanceP2PError(Exception):
    """Raised when the Binance P2P endpoint cannot be reached or parsed."""


class BinanceP2PClient:
    """Small wrapper around the public Binance P2P 'friendly search' endpoint.

    This is the same endpoint the p2p.binance.com web page itself calls.
    It requires no API key, but it is also undocumented/unofficial, so
    treat it as best-effort and expect it may change without notice.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        asset: str,
        fiat: str,
        trade_type: str,
        pay_types: list[str] | None = None,
        rows: int = DEFAULT_ROWS,
    ) -> None:
        self._session = session
        self._asset = asset
        self._fiat = fiat
        self._trade_type = trade_type
        self._pay_types = pay_types or []
        self._rows = rows

    async def async_fetch_offers(self) -> list[dict[str, Any]]:
        """Fetch and normalize the current list of P2P offers, sorted best-first.

        For BUY orders (we are buying crypto) the best price is the lowest.
        For SELL orders (we are selling crypto) the best price is the highest.
        Binance already returns results sorted this way, but we sort
        defensively in case that ever changes.
        """
        payload = {
            "asset": self._asset,
            "fiat": self._fiat,
            "tradeType": self._trade_type,
            "page": 1,
            "rows": self._rows,
            "payTypes": self._pay_types,
            "publisherType": None,
        }

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    BINANCE_P2P_URL, json=payload, headers=_HEADERS
                ) as resp:
                    if resp.status != 200:
                        raise BinanceP2PError(
                            f"Unexpected status {resp.status} from Binance P2P"
                        )
                    data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise BinanceP2PError(f"Error connecting to Binance P2P: {err}") from err
        except TimeoutError as err:
            raise BinanceP2PError("Timeout connecting to Binance P2P") from err
        except ValueError as err:
            # Includes json.JSONDecodeError: Binance/Cloudflare sometimes
            # answers with an HTML challenge page instead of JSON.
            raise BinanceP2PError(
                f"Invalid (non-JSON) response from Binance P2P: {err}"
            ) from err

        if not data or not data.get("success", True) or "data" not in data:
            raise BinanceP2PError(f"Unexpected response payload: {data}")

        offers = [self._normalize(item) for item in data["data"]]
        reverse = self._trade_type == "SELL"
        offers.sort(key=lambda o: o["price"], reverse=reverse)
        return offers

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        adv = item.get("adv", {})
        advertiser = item.get("advertiser", {})

        pay_methods = [
            method.get("tradeMethodName") or method.get("identifier")
            for method in adv.get("tradeMethods", [])
        ]

        return {
            "price": float(adv.get("price", 0)),
            "min_limit": float(adv.get("minSingleTransAmount", 0)),
            # dynamicMaxSingleTransAmount reflects the max limited by the
            # merchant's remaining surplus; fall back to the static limit
            # if it's not present in the response.
            "max_limit": float(
                adv.get("dynamicMaxSingleTransAmount")
                or adv.get("maxSingleTransAmount", 0)
            ),
            "available_amount": float(adv.get("surplusAmount", 0) or adv.get("tradableQuantity", 0)),
            "merchant": advertiser.get("nickName", "unknown"),
            "merchant_rating": advertiser.get("monthFinishRate"),
            "order_count": advertiser.get("monthOrderCount"),
            "payment_methods": pay_methods,
        }


async def async_fetch_payment_methods(
    session: aiohttp.ClientSession, fiat: str
) -> list[dict[str, str]]:
    """Fetch the real list of payment-method identifiers Binance supports
    for a given fiat currency.

    Used by the config flow so the user picks payment methods from a
    validated list instead of typing free-form text: a typo or a name
    that doesn't match Binance's internal identifier would otherwise be
    silently ignored as a filter (payTypes just wouldn't match anything).
    """
    url = f"{BINANCE_P2P_TRADE_METHODS_URL}?fiat={fiat}"

    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(url, headers=_HEADERS) as resp:
                if resp.status != 200:
                    raise BinanceP2PError(
                        f"Unexpected status {resp.status} fetching payment methods"
                    )
                data = await resp.json(content_type=None)
    except aiohttp.ClientError as err:
        raise BinanceP2PError(f"Error fetching payment methods: {err}") from err
    except TimeoutError as err:
        raise BinanceP2PError("Timeout fetching payment methods") from err
    except ValueError as err:
        raise BinanceP2PError(f"Invalid payment methods response: {err}") from err

    if not isinstance(data, list):
        raise BinanceP2PError(f"Unexpected payment methods payload: {data}")

    methods: list[dict[str, str]] = []
    for item in data:
        identifier = item.get("identifier")
        if not identifier:
            continue
        methods.append(
            {"identifier": identifier, "name": item.get("tradeMethodName") or identifier}
        )
    return methods
