# Cloud Run deployment

The GitHub Actions workflow in `.github/workflows/deploy.yml` builds this image with
Cloud Build and deploys it to Cloud Run on every push to `main`.

The live service is `ai-registration-engine` in project `aiex-registration`
(project number `223942147362`), region `europe-west1`:

`https://ai-registration-engine-223942147362.europe-west1.run.app`

## GitHub repository secrets

Configure these GitHub Actions secrets:

- `GCP_SERVICE_ACCOUNT_KEY`: JSON key for a deployer service account.
- `GCP_PROJECT_ID`: Google Cloud project ID (for this service, `aiex-registration`).
- `GCP_REGION`: Cloud Run and Artifact Registry region (for this service, `europe-west1`).
- `GCP_ARTIFACT_REPOSITORY`: Artifact Registry Docker repository name.
- `GCP_CLOUD_RUN_SERVICE`: Cloud Run service name (`ai-registration-engine`).

Application secrets synced into Secret Manager:

| Secret | Required? | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Neon pooled PostgreSQL connection string. |
| `SECRET_KEY` | Yes | Flask secret key (used by `flash()` sessions). |
| `COOKIE_SECRET` | Yes | HMAC key for the `auth_user` login cookie. |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot token for acknowledgements. |
| `TELEGRAM_ALLOWED_CHAT_ID` | Optional | Authorized Telegram chat ID. |
| `TELEGRAM_WEBHOOK_SECRET` | Optional | Telegram webhook secret token. |

The workflow refuses to run if any **required** secret is empty. Optional Telegram
secrets are only synchronized and bound when a value is supplied or a version already
exists — Secret Manager rejects empty payloads, and a bound-but-empty secret aborts
Cloud Run startup with `contains non-UTF8 data` / `cannot be empty`.

Do not place secret values in the repository or the workflow file.

## Required IAM

All of the following are needed; a missing one is the most common cause of a failed
deploy or a revision that will not boot.

**Deployer service account** (the identity behind `GCP_SERVICE_ACCOUNT_KEY`):

- `roles/cloudbuild.builds.editor` — submit Cloud Build jobs.
- `roles/artifactregistry.writer` — push the built image.
- `roles/run.admin` — create Cloud Run revisions and set traffic.
- `roles/iam.serviceAccountUser` — act as the Cloud Run runtime service account.
- `roles/secretmanager.admin` — create secrets, add versions, and grant access.
  Without this the access-granting step cannot bind the runtime service account.

**Cloud Build service account** (`<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`):

- `roles/artifactregistry.writer` — this is a *different* identity from the deployer
  and is required for `gcloud builds submit` to push the image.

**Cloud Run runtime service account** (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`
unless `--service-account` is set):

- `roles/secretmanager.secretAccessor` on each Secret Manager secret. The workflow
  grants this automatically for every bound secret. Without it Cloud Run rejects the
  revision with `Permission denied on secret`.
- `roles/storage.objectAdmin` on the voucher bucket, so Telegram voucher photos can
  be stored and streamed back. See [TELEGRAM_BOT_UI.md](TELEGRAM_BOT_UI.md).

Enable the APIs once per project:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project aiex-registration
```

## Secret Manager secrets

The workflow creates and updates these secrets automatically. To create them by hand:

```bash
printf '%s' 'postgresql://…' | gcloud secrets create DATABASE_URL \
  --data-file=- --replication-policy=automatic --project aiex-registration
```

Notes:

- Always pipe values through `printf '%s'` (or `--data-file`). Do **not** create the
  payload with a shell that emits UTF-16/BOM (for example Windows PowerShell
  `echo x > file`), because Cloud Run aborts the instance with
  `Secret ... contains non-UTF8 data`.
- `gcloud secrets describe` succeeds even for a secret with zero versions. The
  workflow therefore verifies that a `latest` version actually exists before it
  deploys.

## Telegram webhook

After deployment, set the webhook to the real Cloud Run URL:

`https://ai-registration-engine-223942147362.europe-west1.run.app/telegram/webhook`

The URL form is `https://<service>-<project-number>.<region>.run.app`, not
`https://<service>-<region>.run.app`.

Use the same `TELEGRAM_WEBHOOK_SECRET` value when registering the webhook. The app
sends it as the `X-Telegram-Bot-Api-Secret-Token` header and compares it with
`hmac.compare_digest`. If the secret is unset in production the webhook fails closed
with HTTP 403.

### Setting up Telegram end to end

Either let the deploy workflow sync the secrets (add `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_ALLOWED_CHAT_ID` and `TELEGRAM_WEBHOOK_SECRET` as repository secrets and
push), or run the helper from any machine with `gcloud` and `curl`:

```bash
bash scripts/setup_telegram.sh
```

The script prompts for the three values without echoing them (so they never reach
shell history), stores them as UTF-8 Secret Manager secrets, grants
`roles/secretmanager.secretAccessor` to the Cloud Run runtime service account, binds
them to the service with `--update-secrets`, and calls Telegram `setWebhook` /
`getWebhookInfo`. A 403 from `/telegram/webhook` means the secret is not bound; a 200
in `getWebhookInfo` with a non-empty `url` and `last_error_message` absent means
deliveries are arriving.

Telegram only accepts `A-Z a-z 0-9 _ -` in `secret_token`, and the script enforces
that, because a rejected secret makes every delivery fail the HMAC comparison.

## Fixing a failed deployment

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Authenticate to Google Cloud` step fails and every later step is skipped | `GCP_SERVICE_ACCOUNT_KEY` missing, malformed, or its key was revoked | Run `bash scripts/setup_deployer.sh` and store the printed key as the `GCP_SERVICE_ACCOUNT_KEY` repository secret. |
| `Secret Manager API has not been used in project … or it is disabled` | API not enabled | `gcloud services enable secretmanager.googleapis.com --project <project>` |
| `Permission denied on secret … roles/secretmanager.secretAccessor` | Runtime SA lacks access | Grant `roles/secretmanager.secretAccessor` to the runtime SA (the workflow does this). |
| `Secret … contains non-UTF8 data. Instance startup will now abort.` | Secret written with a BOM / UTF-16 | Recreate the version with UTF-8 (use `printf '%s' … \| gcloud secrets versions add`). |
| `Secret Payload cannot be empty` | Empty optional secret | Leave the optional secret uncreated; the app defaults Telegram values to `""`. |
| `COOKIE_SECRET must be configured in production` | Required secret not bound | Create the secret, grant access, and redeploy. |
| HTTP 503 with `Worker failed to boot` in logs | Container crashed on import | Check the Cloud Run logs for the exact `RuntimeError`. |