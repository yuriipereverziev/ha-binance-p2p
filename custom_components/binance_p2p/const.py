"""Constants for the Binance P2P integration."""

DOMAIN = "binance_p2p"

CONF_ASSET = "asset"
CONF_FIAT = "fiat"
CONF_TRADE_TYPE = "trade_type"
CONF_PAY_TYPES = "pay_types"
CONF_CARD_TYPES = "card_types"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DESIRED_AMOUNT = "desired_amount"

DEFAULT_SCAN_INTERVAL = 60  # seconds
MIN_SCAN_INTERVAL = 60  # seconds - lower values risk rate-limiting/bans by Binance
DEFAULT_TRADE_TYPE = "BUY"
DEFAULT_ROWS = 10
# 0 = no filter (show the plain top-of-book offer, regardless of its limits)
DEFAULT_DESIRED_AMOUNT = 0
NUMBER_MAX_AMOUNT = 1_000_000_000
NUMBER_STEP_AMOUNT = 100

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
ATTR_AVAILABLE_AMOUNT = "available_amount"
ATTR_LAST_UPDATED = "last_updated"
ATTR_DESIRED_AMOUNT = "desired_amount"
ATTR_MATCHING_OFFERS = "matching_offers_count"
ATTR_ACTIVE_PAY_TYPES = "active_payment_method_filter"
ATTR_ACTIVE_CARD_TYPES = "active_card_filter"
