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
  initial setup, and sets the *starting* value — from then on it's live,
  dashboard-adjustable state (see `number.<...>_alert_price_from/_to`
  below), same as the desired-amount and active-bank entities. It's
  still editable from the integration's **Configure** (Options) screen
  too, but once you've adjusted it from the dashboard even once, that
  becomes the value that sticks; Options only matters again if you clear
  the integration's stored state. Exposed as the `alert_price_from` /
  `alert_price_to` attributes on the best-price sensor either way, so
  your own automations can reference the current range instead of
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
  limits, rating, payment methods, `adv_no` (Binance's ad identifier) and
  `ad_url` — a direct link to that specific ad on Binance
  (`https://c2c.binance.com/en/adv?code=<adv_no>`), opens in the app if
  installed, in the browser otherwise. Not every offer has an `adv_no`
  from Binance, so the attribute is only present when there's something
  to link to.
- `sensor.<...>_next_update` — timestamp of the next scheduled poll
  (`last successful poll + update interval`). `device_class: timestamp`,
  so the frontend can render it as relative time on its own.
- `number.<...>_desired_amount` — the transaction amount you actually want
  to trade. Set to `0` (default) to just see the plain top-of-book offer
  regardless of its limits. Set it to a real amount and the price sensor
  will instead show the best offer whose min/max limit actually covers
  that amount — useful since many top-of-book offers have a limit too low
  for what you want to trade. Changing this value is instant: it re-filters
  the already-cached offer list without polling Binance again.
- `select.<...>_active_bank` — only created if you restricted payment
  methods during setup (Options → Payment methods). Lets you narrow the
  best-price sensor down to one specific bank at a time, right from the
  dashboard, out of the payment methods you configured. Picking a bank is
  instant, same as `desired_amount` — no extra Binance request, just a
  re-filter of the already-cached offer list. The best-price sensor's
  `selected_bank` attribute mirrors whatever this select entity is
  currently set to (`null`/missing when set to "Все банки", i.e. no extra
  narrowing), so automations can tell which bank the current price
  actually belongs to. See "Notify on a rise, within your configured
  alert range" below — the example automation also fires a one-off alert
  the moment you pick a bank here, if its price already falls inside your
  configured range.
- `number.<...>_alert_price_from` / `number.<...>_alert_price_to` — the
  price-alert range, editable straight from the dashboard (e.g. set
  `from` to `47` and `to` to `48`). Same instant, no-extra-request
  behavior as `desired_amount`: the change is reflected immediately in
  the `alert_price_from`/`alert_price_to` attributes on the best-price
  sensor, which is what any automation checking the range actually
  reads — no need to edit automation YAML when you move these. `0`
  means "no bound on that side". These start out at whatever you set
  during initial setup/Options, but from the first time you touch them
  on the dashboard, their live value takes over — see the note in
  Setup above.

## Linking to the ad on Binance

The best-price sensor exposes `ad_url`, a direct link to the specific ad
(`https://c2c.binance.com/en/adv?code=<adv_no>`). Don't rely on a
templated `tap_action`/`url_path` on `mushroom-template-card` for this —
that's not reliably supported across its versions. A plain `markdown`
card renders a real clickable link and always works:

```yaml
- type: markdown
  content: >
    {% set url = state_attr('sensor.binance_p2p_usdt_uah_sell_best_price', 'ad_url') %}
    {% if url %}
    🔗 [View this ad on Binance]({{ url }})
    {% else %}
    _No ad link available_
    {% endif %}
```

See `examples/dashboard-card.yaml` for this wired into the full dashboard,
including per-entry links in the "Top 3 (24h)" list (via each snapshot's
`adv_no`).

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

### Notify on a rise — or on picking a bank/range — within your alert range

This uses the `alert_price_from` / `alert_price_to` attributes instead of
hardcoding a threshold in the automation, so changing the range doesn't
mean editing YAML. `numeric_state`'s `above`/`below` can't read
attributes, so the range check is a `template` condition instead.

It also has **three triggers**: the usual one on the price sensor, one
on `select.<...>_active_bank`, and one on the two
`number.<...>_alert_price_from/_to` entities — so picking a bank *or*
dragging the range tiles on the dashboard gets you an immediate
notification if the current price is already inside the (possibly
just-changed) range, instead of waiting for the next price move. All
three triggers share most of the same conditions (in range? sensor
actually has an offer?), but `trigger.id` is used to branch the pieces
of logic that *don't* apply to all of them: "price went up" only makes
sense for the price-sensor trigger, and "ignore the value HA restores
at startup" only matters for the select/number triggers.

```yaml
automation:
  - alias: "Binance P2P — ціна продажу зросла"
    description: >-
      Сповіщення при зростанні ціни продажу USDT у межах налаштованого
      діапазону, а також одразу після вибору банку або зміни діапазону
      на дашборді, якщо поточна ціна вже потрапляє у нього
    triggers:
      - trigger: state
        entity_id: sensor.binance_p2p_usdt_uah_sell_best_price
        id: price_update
      - trigger: state
        entity_id: select.binance_p2p_usdt_uah_sell_active_bank
        id: bank_selected
      - trigger: state
        entity_id:
          - number.binance_p2p_usdt_uah_sell_alert_price_from
          - number.binance_p2p_usdt_uah_sell_alert_price_to
        id: range_changed
    conditions:
      # Sensor actually has an offer right now
      - condition: template
        value_template: >
          {{ states('sensor.binance_p2p_usdt_uah_sell_best_price')
             not in ['unknown', 'unavailable'] }}
      # price_update only: price actually went up since the previous state
      - condition: template
        value_template: >
          {% if trigger.id == 'price_update' %}
            {% set old = trigger.from_state.state %}
            {% set new = trigger.to_state.state %}
            {{ old not in ['unknown', 'unavailable', none] and
               new not in ['unknown', 'unavailable', none] and
               (new | float) > (old | float) }}
          {% else %}
            true
          {% endif %}
      # bank_selected / range_changed only: ignore the state HA restores
      # at startup
      - condition: template
        value_template: >
          {% if trigger.id in ['bank_selected', 'range_changed'] %}
            {{ trigger.from_state is not none and
               trigger.from_state.state not in ['unknown', 'unavailable'] }}
          {% else %}
            true
          {% endif %}
      # Current price (already scoped to whichever bank/range is
      # currently set) is within the configured alert range - reads the
      # live sensor state/attributes so it works the same for all three
      # triggers.
      - condition: template
        value_template: >
          {% set entity = 'sensor.binance_p2p_usdt_uah_sell_best_price' %}
          {% set price = states(entity) | float(0) %}
          {% set alert_from = state_attr(entity, 'alert_price_from') | float(0) %}
          {% set alert_to = state_attr(entity, 'alert_price_to') | float(0) %}
          {{ (alert_from == 0 or price > alert_from) and
             (alert_to == 0 or price < alert_to) }}
      # Optional: only during waking hours
      - condition: time
        after: "09:00:00"
        before: "21:00:00"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: >-
            {% if trigger.id == 'bank_selected' %}
              🏦 Ціна для обраного банку
            {% elif trigger.id == 'range_changed' %}
              🎯 Ціна вже у новому діапазоні
            {% else %}
              📈 Ціна продажу зросла
            {% endif %}
          message: >
            {% set entity = 'sensor.binance_p2p_usdt_uah_sell_best_price' %}
            {% set select_entity = 'select.binance_p2p_usdt_uah_sell_active_bank' %}
            {% set new = states(entity) | float %}
            {% set bank = state_attr(entity, 'selected_bank') or states(select_entity) or 'усі банки' %}
            {% set alert_from = state_attr(entity, 'alert_price_from') | float(0) %}
            {% set alert_to = state_attr(entity, 'alert_price_to') | float(0) %}
            {% set merchant = state_attr(entity, 'merchant') %}
            {% set rating = (state_attr(entity, 'merchant_rating') or 0) * 100 %}
            {% set min_l = state_attr(entity, 'min_limit') | round(0) %}
            {% set max_l = state_attr(entity, 'max_limit') | round(0) %}
            {% set avail = state_attr(entity, 'available_amount') | round(0) %}
            {% if trigger.id == 'bank_selected' %}
            Банк: {{ bank }} — поточна ціна {{ new }} грн (у межах {{ alert_from }}–{{ alert_to }})
            {% elif trigger.id == 'range_changed' %}
            Діапазон: {{ alert_from }}–{{ alert_to }} грн — поточна ціна {{ new }} грн вже підходить
            Банк: {{ bank }}
            {% else %}
            {% set old = trigger.from_state.state | float %}
            Ціна виросла: {{ old }} → {{ new }} грн (+{{ (new - old) | round(2) }})
            Банк: {{ bank }}
            {% endif %}
            Продавець: {{ merchant }} (⭐ {{ rating | round(1) }}%)
            Ліміти: {{ min_l }}–{{ max_l }} грн, доступно {{ avail }} USDT
    mode: single
```

A ready-to-copy version of this automation also lives at
[`examples/price-alert-automation.yaml`](examples/price-alert-automation.yaml).
If you didn't restrict payment methods during setup, there's no
`select.<...>_active_bank` entity to trigger on — just delete the
`bank_selected` trigger and its two dedicated condition branches; the
`price_update` trigger works standalone.

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
