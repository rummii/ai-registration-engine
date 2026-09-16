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

- `LineItem` must exactly match a configured budget line item.
- `YYYY` is the fiscal year from 2000 through 2100.
- `MM` is a month from `01` through `12`.
- `Amount` is a finite, non-negative number.
- Values are separated by the pipe character (`|`).

The webhook accepts updates only from `TELEGRAM_ALLOWED_CHAT_ID`. Valid messages update the matching fiscal-year/month/line-item actual and return a confirmation. Invalid messages return an error without changing budget data.
