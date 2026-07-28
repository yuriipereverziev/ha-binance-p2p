"""Thin async client for the public Binance P2P search endpoint."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import BINANCE_P2P_URL, DEFAULT_ROWS

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


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
                    BINANCE_P2P_URL, json=payload
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
            "max_limit": float(adv.get("maxSingleTransAmount", 0)),
            "available_amount": float(adv.get("surplusAmount", 0) or adv.get("tradableQuantity", 0)),
            "merchant": advertiser.get("nickName", "unknown"),
            "merchant_rating": advertiser.get("monthFinishRate"),
            "order_count": advertiser.get("monthOrderCount"),
            "payment_methods": pay_methods,
        }
