"""Thin async client for the public Binance P2P search endpoint."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import (
    BINANCE_P2P_TRADE_METHODS_URL,
    BINANCE_P2P_URL,
    DEFAULT_ROWS,
    PER_PAY_TYPE_ROWS,
)

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
        card_types: list[str] | None = None,
        rows: int = DEFAULT_ROWS,
    ) -> None:
        self._session = session
        self._asset = asset
        self._fiat = fiat
        self._trade_type = trade_type
        self._pay_types = pay_types or []
        # Second, independent condition: offer must ALSO support at least
        # one of these "card for crediting" identifiers. Kept separate from
        # _pay_types (rather than merged into one list) because the two are
        # ANDed together client-side - see async_fetch_offers().
        self._card_types = card_types or []
        self._rows = rows

    async def async_fetch_offers(self) -> list[dict[str, Any]]:
        """Fetch and normalize the current list of P2P offers, sorted best-first.

        For BUY orders (we are buying crypto) the best price is the lowest.
        For SELL orders (we are selling crypto) the best price is the highest.
        Binance already returns results sorted this way, but we sort
        defensively in case that ever changes.
        """
        # Binance's own payTypes filter is OR-based (matches offers
        # supporting ANY of the given identifiers) AND the result is
        # capped at `rows` (DEFAULT_ROWS) total, ranked by price across
        # ALL of those identifiers combined - not per identifier. With
        # more than one identifier configured, whichever bank happens to
        # be the most price-competitive right now can fill the entire
        # window, leaving zero results for a less competitive (but
        # perfectly real) bank you also configured - e.g. PrivatBank
        # offers outprice Monobank ones and take all 10 slots, so
        # picking Monobank client-side afterwards finds nothing even
        # though Monobank ads do exist further down Binance's book.
        #
        # So: with more than one identifier, query each one separately
        # (in parallel) with a small `rows` each, guaranteeing every
        # configured bank/card gets a fair shot at being represented in
        # the cached data - not just the market leader. With 0 or 1
        # identifiers there's nothing to starve each other, so a single
        # combined request is enough (and cheaper).
        all_types = sorted(set(self._pay_types) | set(self._card_types))

        if len(all_types) > 1:
            results = await asyncio.gather(
                *(self._fetch_page([t], PER_PAY_TYPE_ROWS) for t in all_types),
                return_exceptions=True,
            )
            raw_items: list[dict[str, Any]] = []
            seen_adv_no: set[str] = set()
            errors: list[BaseException] = []
            for result in results:
                if isinstance(result, BaseException):
                    errors.append(result)
                    continue
                for item in result:
                    adv_no = item.get("adv", {}).get("advNo")
                    if adv_no and adv_no in seen_adv_no:
                        continue
                    if adv_no:
                        seen_adv_no.add(adv_no)
                    raw_items.append(item)
            # Only give up if every single per-bank request failed - a
            # transient error on one bank's request shouldn't sink data
            # for the others that did succeed.
            if errors and len(errors) == len(results):
                raise BinanceP2PError(
                    f"Error connecting to Binance P2P: {errors[0]}"
                ) from errors[0]
        else:
            raw_items = await self._fetch_page(all_types, self._rows)

        offers = [self._normalize(item) for item in raw_items]

        if self._pay_types:
            offers = [
                o for o in offers
                if set(o["payment_method_ids"]) & set(self._pay_types)
            ]
        if self._card_types:
            offers = [
                o for o in offers
                if set(o["payment_method_ids"]) & set(self._card_types)
            ]

        reverse = self._trade_type == "SELL"
        offers.sort(key=lambda o: o["price"], reverse=reverse)
        return offers

    async def _fetch_page(
        self, pay_types: list[str], rows: int
    ) -> list[dict[str, Any]]:
        """POST one search request to Binance and return the raw `data` list
        (not yet normalized). Shared by the single-request and the
        per-identifier fan-out in async_fetch_offers()."""
        payload = {
            "asset": self._asset,
            "fiat": self._fiat,
            "tradeType": self._trade_type,
            "page": 1,
            "rows": rows,
            "payTypes": pay_types,
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

        return data["data"]

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        adv = item.get("adv", {})
        advertiser = item.get("advertiser", {})

        trade_methods = adv.get("tradeMethods", [])
        pay_methods = [
            method.get("tradeMethodName") or method.get("identifier")
            for method in trade_methods
        ]
        # Raw identifiers (e.g. "Monobank", "PrivatBank") used for matching
        # against the config's pay_types/card_types filters - separate from
        # pay_methods above, which is the human-readable display list.
        pay_method_ids = [
            method.get("identifier")
            for method in trade_methods
            if method.get("identifier")
        ]

        return {
            "price": float(adv.get("price", 0)),
            "adv_no": adv.get("advNo"),
            "payment_method_ids": pay_method_ids,
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

    # The response is wrapped like the search endpoint's, not a bare list:
    # {"code": "000000", "message": None, "data": [...], "success": True}.
    if not isinstance(data, dict) or not data.get("success", True):
        raise BinanceP2PError(f"Unexpected payment methods payload: {data}")

    method_list = data.get("data")
    if not isinstance(method_list, list):
        raise BinanceP2PError(f"Unexpected payment methods payload: {data}")

    methods: list[dict[str, str]] = []
    for item in method_list:
        identifier = item.get("identifier")
        if not identifier:
            continue
        methods.append(
            {"identifier": identifier, "name": item.get("tradeMethodName") or identifier}
        )
    return methods