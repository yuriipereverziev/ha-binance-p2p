"""Constants for the Binance P2P integration."""

DOMAIN = "binance_p2p"

CONF_ASSET = "asset"
CONF_FIAT = "fiat"
CONF_TRADE_TYPE = "trade_type"
CONF_PAY_TYPES = "pay_types"
CONF_CARD_TYPES = "card_types"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DESIRED_AMOUNT = "desired_amount"
CONF_ALERT_PRICE_FROM = "alert_price_from"
CONF_ALERT_PRICE_TO = "alert_price_to"

DEFAULT_SCAN_INTERVAL = 60  # seconds
MIN_SCAN_INTERVAL = 60  # seconds - lower values risk rate-limiting/bans by Binance
DEFAULT_TRADE_TYPE = "BUY"
DEFAULT_ROWS = 10
# Used instead of DEFAULT_ROWS when querying Binance separately per
# payment-method identifier (see api.py's async_fetch_offers) - only
# need enough rows to find that one identifier's best offer(s), not a
# full top-10 window per bank.
PER_PAY_TYPE_ROWS = 5
# 0 = no filter (show the plain top-of-book offer, regardless of its limits)
DEFAULT_DESIRED_AMOUNT = 0
NUMBER_MAX_AMOUNT = 1_000_000_000
NUMBER_STEP_AMOUNT = 100
# 0/0 = no price-alert range configured - automations relying on the
# alert_price_from/alert_price_to attributes should treat that as "no
# range filter" rather than a literal 0..0 window.
DEFAULT_ALERT_PRICE_FROM = 0
DEFAULT_ALERT_PRICE_TO = 0
NUMBER_MAX_PRICE = 1_000_000
NUMBER_STEP_PRICE = 0.01

TRADE_TYPES = ["BUY", "SELL"]

BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
BINANCE_P2P_TRADE_METHODS_URL = (
    "https://p2p.binance.com/bapi/c2c/v1/public/c2c/agent/trade-methods"
)

ATTR_MERCHANT = "merchant"
ATTR_MIN_LIMIT = "min_limit"
ATTR_MAX_LIMIT = "max_limit"
ATTR_MERCHANT_RATING = "merchant_rating"
ATTR_ORDER_COUNT = "order_count"
ATTR_PAYMENT_METHODS = "payment_methods"
ATTR_PAYMENT_METHOD_IDS = "payment_method_ids"
ATTR_AVAILABLE_AMOUNT = "available_amount"
ATTR_LAST_UPDATED = "last_updated"
ATTR_SCAN_INTERVAL = "scan_interval"
ATTR_DESIRED_AMOUNT = "desired_amount"
ATTR_MATCHING_OFFERS = "matching_offers_count"
ATTR_ACTIVE_PAY_TYPES = "active_payment_method_filter"
ATTR_ACTIVE_CARD_TYPES = "active_card_filter"
# The live, single-bank pick from the select entity (None = no extra
# narrowing beyond the configured pay_types/card_types) - distinct from
# ATTR_ACTIVE_PAY_TYPES above, which reflects the full configured list.
ATTR_SELECTED_BANK = "selected_bank"
ATTR_TOP_OFFERS_24H = "top_offers"
ATTR_ALERT_PRICE_FROM = "alert_price_from"
ATTR_ALERT_PRICE_TO = "alert_price_to"
ATTR_ADV_NO = "adv_no"
ATTR_AD_URL = "ad_url"

# Binance's own link format for opening a specific P2P ad (web, or the app
# via universal link if installed) - see
# https://github.com/binance/binance-skills-hub - "provide a direct link
# to the specific ad using the adNo": https://c2c.binance.com/en/adv?code={adNo}
AD_URL_TEMPLATE = "https://c2c.binance.com/en/adv?code={adv_no}"