# ha-binance-p2p

Home Assistant custom integration that tracks the best Binance P2P offer
for a given asset/fiat/trade-type combination.

## Features (MVP)

- Installable via HACS (custom repository)
- Configured entirely through the Home Assistant UI (Config Flow)
- Sensor exposing the best P2P price
- Attributes: merchant, min/max limits, merchant rating, order count, payment methods, available amount
- Configurable auto-refresh interval
- Works out of the box with HA automations (`numeric_state` triggers, etc.)

## Installation

### HACS (custom repository, until this is in the default store)

1. HACS → Integrations → menu (⋮) → **Custom repositories**
2. Add this repo URL, category **Integration**
3. Install "Binance P2P", restart Home Assistant

### Manual

Copy `custom_components/binance_p2p` into your HA `config/custom_components/` folder and restart.

## Setup

Settings → Devices & Services → Add Integration → **Binance P2P**.
You'll be asked for:

- Asset (e.g. `USDT`)
- Fiat (e.g. `UAH`)
- Trade type (`BUY` or `SELL`)
- Payment methods (optional filter)
- Update interval in seconds (minimum 60s — lower values risk being
  rate-limited or temporarily blocked by Binance)

## Entities

- `sensor.<...>_best_price` — price of the best offer (or the best offer
  that covers the desired amount, see below). Attributes include merchant,
  limits, rating, payment methods, etc.
- `number.<...>_desired_amount` — the transaction amount you actually want
  to trade. Set to `0` (default) to just see the plain top-of-book offer
  regardless of its limits. Set it to a real amount and the price sensor
  will instead show the best offer whose min/max limit actually covers
  that amount — useful since many top-of-book offers have a limit too low
  for what you want to trade. Changing this value is instant: it re-filters
  the already-cached offer list without polling Binance again.

## Example automation

```yaml
automation:
  - alias: Notify when USDT/UAH buy price drops
    trigger:
      - platform: numeric_state
        entity_id: sensor.binance_p2p_usdt_uah_buy_best_price
        below: 42.0
    action:
      - service: notify.mobile_app_your_phone
        data:
          message: "Best USDT/UAH buy offer just dropped below 42!"
```

## Notes

This integration uses the same public, unofficial endpoint the
p2p.binance.com web page itself calls. There is no official public API
for P2P data, so this may break if Binance changes that endpoint.

## License

MIT
