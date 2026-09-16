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

The deployer needs permission to submit Cloud Build jobs, write to Artifact Registry,
deploy Cloud Run revisions, and impersonate or use the runtime service account.

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