"""Constants for the Binance P2P integration."""

DOMAIN = "binance_p2p"

CONF_ASSET = "asset"
CONF_FIAT = "fiat"
CONF_TRADE_TYPE = "trade_type"
CONF_PAY_TYPES = "pay_types"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_TRADE_TYPE = "BUY"
DEFAULT_ROWS = 10

TRADE_TYPES = ["BUY", "SELL"]

BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

ATTR_MERCHANT = "merchant"
ATTR_MIN_LIMIT = "min_limit"
ATTR_MAX_LIMIT = "max_limit"
ATTR_MERCHANT_RATING = "merchant_rating"
ATTR_ORDER_COUNT = "order_count"
ATTR_PAYMENT_METHODS = "payment_methods"
ATTR_AVAILABLE_AMOUNT = "available_amount"
ATTR_LAST_UPDATED = "last_updated"
