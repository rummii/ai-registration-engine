# Telegram Budget Actuals

The budget controller accepts actual expense updates from the configured Telegram chat.

## Message format

```text
BUDGET|LineItem|YYYY|MM|Amount
```

Example:

```text
BUDGET|Marketing|2026|09|25000
```

- `BUDGET` is matched case-insensitively (`budget` and `Budget` also work).
- Values are separated by the **ASCII pipe character** `|` (U+007C).
- `LineItem` must match a configured budget line item **exactly, including case**.
- `YYYY` is the fiscal year from 2000 through 2100.
- `MM` is a month from `01` through `12`.
- `Amount` is a finite, non-negative number.

## Valid line items

Nearly all of these names contain no spaces, but `/` is significant — `Service/Maintenance`
is a single item, not two.

| Category | Line items |
| --- | --- |
| Other Expenses | `Power`, `Water`, `IT`, `Communication`, `Stationery`, `Service/Maintenance`, `Misc`, `Other` |
| Promotion Expenses | `Marketing`, `Promotions`, `Collaterals`, `Printing/Advertising`, `Travel`, `Transportation` |
| Payroll & Pilotage | `Pilotage`, `Payroll`, `Misc`, `Other` |
| Fixed Costs | `Rent`, `Tax` |

`Misc` and `Other` are shared by more than one category, so an actual recorded
against them cannot be attributed to a single category.

## Troubleshooting rejections

The bot replies with the specific problem, so no log digging is needed.

| Reply | Cause |
| --- | --- |
| `Expected 5 fields separated by '|' … but found 1` | The separators are not pipe characters. On phone keyboards `\|` is often unavailable and an autocorrect or a lookalike glyph such as `¦` (U+00A6), `∣` (U+2223), `｜` (U+FF5C) or a capital `I` gets substituted. |
| `Expected … but found 4` | A field is missing. |
| `Message must start with 'BUDGET' but started with '…'` | Wrong leading keyword. |
| `Unknown budget line item: 'rent'. Valid items: …` | Line items are case-sensitive; use the exact names above. |
| `Month must be between 1 and 12.` | Month out of range. |
| `Amount must be a finite, non-negative number.` | Negative, blank, or non-numeric amount. |

## Behaviour

The webhook accepts updates only from `TELEGRAM_ALLOWED_CHAT_ID`. Valid messages update
the matching fiscal-year/month/line-item actual, are de-duplicated by Telegram
`update_id`, and return a confirmation. Invalid messages return an error without
changing budget data.
