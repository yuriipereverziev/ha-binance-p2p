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
- Update interval in seconds (minimum 60s — lower values risk being
  rate-limited or temporarily blocked by Binance)
- Price-alert range (`from` / `to`) — the range you actually care about
  being notified in. Leave both at `0` to skip it. This is asked once at
  initial setup, but can be changed later too, from the integration's
  **Configure** (Options) screen. The values aren't used by the
  integration itself — they're exposed as the `alert_price_from` /
  `alert_price_to` attributes on the best-price sensor, so your own
  automations can reference the range you configured instead of
  hardcoding numbers in the automation's YAML (see the example below).

After that, if Binance's payment-method list for your fiat can be fetched,
you'll see a second step to optionally pick specific payment methods from
a real, validated list (instead of typing free text that might not match
Binance's internal identifiers and get silently ignored). Leave it empty
to allow any payment method. If that list can't be fetched (e.g. Binance
temporarily unreachable), this step is skipped automatically and no
payment-method filter is applied.

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

## Example automations

### Simple: fixed threshold

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

### Notify on a rise, within your configured alert range

This uses the `alert_price_from` / `alert_price_to` attributes (set once
during setup, editable later in Options) instead of hardcoding a
threshold in the automation, so changing the range doesn't mean editing
YAML. `numeric_state`'s `above`/`below` can't read attributes, so the
range check is a `template` condition instead:

```yaml
automation:
  - alias: "Binance P2P — ціна продажу зросла"
    description: >-
      Сповіщення при зростанні ціни продажу USDT у межах налаштованого
      діапазону (з урахуванням фільтрів способів оплати)
    triggers:
      - trigger: state
        entity_id: sensor.binance_p2p_usdt_uah_sell_best_price
    conditions:
      # Price actually went up since the previous state
      - condition: template
        value_template: >
          {% set old = trigger.from_state.state %}
          {% set new = trigger.to_state.state %}
          {{ old not in ['unknown', 'unavailable', none] and
             new not in ['unknown', 'unavailable', none] and
             (new | float) > (old | float) }}
      # New price is within the alert_price_from/alert_price_to range
      # configured for this entity (0 on either side = no bound there)
      - condition: template
        value_template: >
          {% set entity = 'sensor.binance_p2p_usdt_uah_sell_best_price' %}
          {% set new = trigger.to_state.state | float %}
          {% set alert_from = state_attr(entity, 'alert_price_from') | float(0) %}
          {% set alert_to = state_attr(entity, 'alert_price_to') | float(0) %}
          {{ (alert_from == 0 or new > alert_from) and
             (alert_to == 0 or new < alert_to) }}
      # Optional: only if the offer matches your payment/card filters
      - condition: template
        value_template: >
          {% set entity = 'sensor.binance_p2p_usdt_uah_sell_best_price' %}
          {% set active_pay = state_attr(entity, 'active_payment_method_filter') or [] %}
          {% set active_cards = state_attr(entity, 'active_card_filter') or [] %}
          {% set offer_ids = state_attr(entity, 'payment_method_ids') or [] %}
          {{ (active_pay | length == 0 or active_pay | select('in', offer_ids) | list | length > 0)
             and
             (active_cards | length == 0 or active_cards | select('in', offer_ids) | list | length > 0) }}
      # Optional: only during waking hours
      - condition: time
        after: "09:00:00"
        before: "21:00:00"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "📈 Ціна продажу зросла"
          message: >
            {% set entity = 'sensor.binance_p2p_usdt_uah_sell_best_price' %}
            {% set old = trigger.from_state.state | float %}
            {% set new = trigger.to_state.state | float %}
            {% set merchant = state_attr(entity, 'merchant') %}
            {% set rating = (state_attr(entity, 'merchant_rating') or 0) * 100 %}
            {% set min_l = state_attr(entity, 'min_limit') | round(0) %}
            {% set max_l = state_attr(entity, 'max_limit') | round(0) %}
            {% set avail = state_attr(entity, 'available_amount') | round(0) %}
            {% set active_pay = state_attr(entity, 'active_payment_method_filter') or [] %}
            {% set active_cards = state_attr(entity, 'active_card_filter') or [] %}
            Ціна виросла: {{ old }} → {{ new }} грн (+{{ (new - old) | round(2) }})
            Продавець: {{ merchant }} (⭐ {{ rating | round(1) }}%)
            Ліміти: {{ min_l }}–{{ max_l }} грн, доступно {{ avail }} USDT
            Фільтр: {{ (active_pay + active_cards) | join(', ') if (active_pay or active_cards) else 'без обмежень' }}
    mode: single
```

A ready-to-copy version of this automation also lives at
[`examples/price-alert-automation.yaml`](examples/price-alert-automation.yaml).

**What changed compared to hardcoding `above: 47` / `below: 48` in a
`numeric_state` condition:** that pattern can't reference an entity's
own attributes, so the range was frozen in the automation's YAML. Now
the range lives in the integration's config (settable at setup and
editable later in Options), the sensor exposes it as
`alert_price_from`/`alert_price_to`, and the automation reads it via a
`template` condition — change the range once in the UI and every
automation that reads these attributes picks it up, no YAML edits
needed. Also replace `notify.notify` with your actual notify service
(e.g. `notify.mobile_app_<your_device>`) — a bare `notify.notify` only
works if you have a single default notify target configured.

## Notes

This integration uses the same public, unofficial endpoint the
p2p.binance.com web page itself calls. There is no official public API
for P2P data, so this may break if Binance changes that endpoint.

## License

MIT
