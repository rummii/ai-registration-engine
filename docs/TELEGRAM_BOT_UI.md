# Telegram Bot UI

The bot has a button-driven interface for logging expenses, so nobody has to
remember line item names or type a pipe-separated command. The typed
`BUDGET|...` format still works and is documented in
[TELEGRAM_BUDGET_FORMAT.md](TELEGRAM_BUDGET_FORMAT.md).

## The flow

```
/expense  →  [Other Expenses] [Promotion Expenses] [Payroll & Pilotage] [Fixed Costs]
          →  [Marketing] [Promotions] [Collaterals] [Printing/Advertising] ...
          →  [2025] [· 2026 ·] [2027]   then   [• Sep •] [Oct 2026] [Nov 2026] ...
          →  "Send the amount as a plain number"
          →  "Send the receipt photo, or tap Skip"
          →  [✅ Save] [✖ Cancel]  /  [💵 Change amount] [📸 Replace voucher]
          →  "✅ Logged 25,000.00 for Marketing — Sep 2026 total is now 25,000.00."
```

Commands:

| Command | Effect |
| --- | --- |
| `/start`, `/menu` | Main menu |
| `/expense`, `/log`, `/add` | Start the button flow |
| `/summary`, `/month` | Per-line-item totals for the current month |
| `/skip` | Skip the voucher while the bot is asking for one |
| `/cancel`, `/stop` | Discard the draft; nothing is saved |
| `/help` | Explains the flow |

## Amounts are added, not replaced

This is the one place the two interfaces differ, and it is deliberate:

- **Button flow** — each entry is *added* to that month's actual, because logging
  an expense should accumulate. Every entry is also written to
  `expense_transactions` with a running total.
- **Typed `BUDGET|...`** — *sets* the month's actual to the value given, matching
  its original documented behaviour.

Use `/cancel` and re-log, or the typed format, to correct a mistaken amount.

## Where the data goes

| Table | Purpose |
| --- | --- |
| `expense_transactions` | One row per logged expense, with the running total and voucher object name. `telegram_update_id` is unique so a Telegram redelivery cannot double-count. |
| `budget_actuals_cache` | The month's running actual per line item, which is what the budget page charts. Updated with an upsert so a month with no pre-seeded row still works. |
| `budget_actuals_audit_log` | Mirrors each entry so the budget page's "actuals live" badge stays accurate. |
| `telegram_sessions` | The in-progress draft, keyed by `chat_id`. |

## Why the draft lives in the database

Cloud Run runs several stateless instances behind a load balancer with no sticky
routing, so the instance that handles a button press is often not the one that drew
the keyboard. Anything cached in process memory would be lost mid-flow. The draft is
therefore read and written from `telegram_sessions` on every step.

There is deliberately no "menu" step: the resting state is the absence of a row, so
cancelling cannot leave stale state behind.

## Vouchers

Photos are stored in Cloud Storage, not on disk. The container filesystem is
ephemeral and per-instance, so a local file would disappear on the next deploy or
cold start. (The previous polling bot wrote vouchers to a local directory, which
would have silently lost them.)

- Bucket: `aiex-registration-vouchers-223942147362` (region `europe-west1`, private)
- Object name: `vouchers/<YYYY>/<MM>/<YYYYMMDD_HHMMSS>_<chat_id>.jpg`
- Retrieval: `/admin/voucher/<object_name>`, admin-only, streamed from the bucket
  so no signed URLs or token-signing permission are needed
- The budget page lists recent Telegram expenses with a **View receipt** link

The Cloud Run runtime service account needs `roles/storage.objectAdmin` on the
bucket:

```bash
gcloud storage buckets add-iam-policy-binding gs://aiex-registration-vouchers-223942147362 \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin" \
  --project aiex-registration
```

If the bucket is unset or the upload fails, the expense is still saved and the bot
says the voucher was not stored. A missing photo never loses the amount.

## Troubleshooting

### Buttons render but tapping them does nothing

This is almost always the webhook's `allowed_updates` filter. Button taps arrive as
`callback_query` updates, and if the webhook was registered with
`allowed_updates` set to only `["message","edited_message"]`, Telegram silently
never delivers them: no error, no log entry, no pending update. The keyboards render
because those are ordinary messages.

Check and fix (the setup script no longer sets a filter at all):

```bash
TOKEN=$(gcloud secrets versions access latest --secret TELEGRAM_BOT_TOKEN --project <project>)
curl -s "https://api.telegram.org/bot${TOKEN}/getWebhookInfo"   # inspect allowed_updates
```

If `allowed_updates` is present and excludes `callback_query`, re-run
`scripts/setup_telegram.sh`, which re-registers without a filter.

### Telegram reports "Wrong response from the webhook: 403"

The app returned 403, which makes Telegram retry the same update forever, filling the
logs with ~3 ms 403s and leaving `pending_update_count` above zero. There are two
legitimate 403 paths:

- `Unauthorized webhook request.` — the `X-Telegram-Bot-Api-Secret-Token` header
  does not match `TELEGRAM_WEBHOOK_SECRET`.
- `Unauthorized Telegram chat.` — the sender is not `TELEGRAM_ALLOWED_CHAT_ID`.

Update kinds that carry no chat (inline queries, polls) and kinds we do not handle
from the allowed chat (`my_chat_member`) now return **200 `{"ok":true,"ignored":true}`**
precisely so Telegram stops retrying them. Only a genuinely unauthorised chat is
rejected.

### Checking what the webhook actually received

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="ai-registration-engine" httpRequest.requestUrl:"/telegram/webhook"' \
  --project <project> --limit 20 --freshness=30m \
  --format="table(timestamp,httpRequest.status,httpRequest.latency)"
```

A rejected request returns in a few milliseconds, because the check runs before any
work. A real delivery takes tenths of a second because it calls the Telegram API.

## Line items come from one place

The keyboards are generated from `FINANCIAL_STRUCTURE` in
[`budget_structure.py`](../budget_structure.py), which the web budget page also
imports. The previous bot kept its own copy and had drifted to
`Service/Maintainance` and `Colletrals`, so those actuals never appeared on the
budget page. `tests/test_telegram_ui.py` now asserts every item is addressable and
resolves back to its exact name.
