# Cloud Run deployment

The GitHub Actions workflow in `.github/workflows/deploy.yml` builds this image with
Cloud Build and deploys it to Cloud Run on every push to `main`.

## GitHub repository secrets

Configure these GitHub Actions secrets:

- `GCP_SERVICE_ACCOUNT_KEY`: JSON key for a deployer service account.
- `GCP_PROJECT_ID`: Google Cloud project ID.
- `GCP_REGION`: Cloud Run and Artifact Registry region, normally `us-east1`.
- `GCP_ARTIFACT_REPOSITORY`: Artifact Registry Docker repository name.
- `GCP_CLOUD_RUN_SERVICE`: Cloud Run service name.
- `DATABASE_URL`: Neon pooled PostgreSQL connection string.
- `SECRET_KEY`: random Flask secret key.
- `COOKIE_SECRET`: random cookie-signing secret.
- `TELEGRAM_BOT_TOKEN`: rotated Telegram bot token.
- `TELEGRAM_ALLOWED_CHAT_ID`: authorized Telegram chat ID.
- `TELEGRAM_WEBHOOK_SECRET`: random Telegram webhook secret token.

The deployer needs permission to submit Cloud Build jobs, write to Artifact Registry,
deploy Cloud Run revisions, and create/update Secret Manager secrets. The workflow
synchronizes the six application secrets from GitHub Actions into Secret Manager
before deployment.
The workflow verifies that all required Secret Manager secrets exist before it builds
or deploys a revision.

## Secret Manager secrets

Create these Secret Manager secrets and grant the Cloud Run runtime service account
the Secret Manager Secret Accessor role:

- `DATABASE_URL`
- `SECRET_KEY`
- `COOKIE_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `TELEGRAM_WEBHOOK_SECRET`

Do not place secret values in the repository or GitHub workflow. After deployment,
set the Telegram webhook URL to:

`https://SERVICE-REGION.run.app/telegram/webhook`

Use the same `TELEGRAM_WEBHOOK_SECRET` value when configuring the Telegram webhook.

## Fixing a missing-secret boot failure

If Cloud Run logs show `COOKIE_SECRET must be configured in production`, create the
missing Secret Manager secret and grant the Cloud Run runtime service account access
before rerunning the GitHub workflow. Repeat for every required secret listed above.