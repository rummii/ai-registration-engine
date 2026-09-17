#!/usr/bin/env bash
#
# Configure the Telegram integration for the ai-registration-engine Cloud Run service.
#
# Usage:
#   bash scripts/setup_telegram.sh
#
# The script prompts for the three Telegram values without echoing them, then:
#   1. stores them as UTF-8 Secret Manager secrets
#   2. grants the Cloud Run runtime service account read access
#   3. binds them to the Cloud Run service
#   4. registers the Telegram webhook and prints getWebhookInfo
#
# Safe to re-run: existing secrets receive a new version, IAM bindings are
# idempotent, and setWebhook replaces any previous registration.
#
# Override defaults with environment variables if needed:
#   PROJECT_ID=aiex-registration REGION=europe-west1 SERVICE=ai-registration-engine \
#     bash scripts/setup_telegram.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-aiex-registration}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-ai-registration-engine}"
SECRET_NAMES=(TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_CHAT_ID TELEGRAM_WEBHOOK_SECRET)

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "--> $*"; }

command -v gcloud >/dev/null 2>&1 || die "gcloud is not installed."
command -v curl >/dev/null 2>&1 || die "curl is not installed."

ACTIVE_ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
[ -n "${ACTIVE_ACCOUNT}" ] || die "No active gcloud account. Run: gcloud auth login"
info "Project: ${PROJECT_ID}   Region: ${REGION}   Service: ${SERVICE}"
info "gcloud account: ${ACTIVE_ACCOUNT}"
echo

# ---------------------------------------------------------------- input ----
read -rsp "TELEGRAM_BOT_TOKEN (from @BotFather, hidden): " TELEGRAM_BOT_TOKEN; echo
read -rsp "TELEGRAM_ALLOWED_CHAT_ID (digits, hidden): " TELEGRAM_ALLOWED_CHAT_ID; echo
read -rsp "TELEGRAM_WEBHOOK_SECRET (Enter to auto-generate, hidden): " TELEGRAM_WEBHOOK_SECRET; echo

[ -n "${TELEGRAM_BOT_TOKEN}" ] || die "TELEGRAM_BOT_TOKEN cannot be empty."
[ -n "${TELEGRAM_ALLOWED_CHAT_ID}" ] || die "TELEGRAM_ALLOWED_CHAT_ID cannot be empty (Secret Manager rejects empty payloads)."

if ! printf '%s' "${TELEGRAM_ALLOWED_CHAT_ID}" | grep -Eq '^-?[0-9]+$'; then
  die "TELEGRAM_ALLOWED_CHAT_ID must be a numeric Telegram chat id."
fi

# Telegram restricts secret_token to A-Z a-z 0-9 _ and - (1-256 characters).
# A base64 value that still carries + / or = is rejected by setWebhook, and a
# rejected secret means every delivery fails the HMAC comparison in app.py.
# Generate a compliant value instead of letting an arbitrary string through.
generate_webhook_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
  fi
}

while :; do
  if [ -z "${TELEGRAM_WEBHOOK_SECRET}" ]; then
    TELEGRAM_WEBHOOK_SECRET="$(generate_webhook_secret)"
    info "No value entered; generated TELEGRAM_WEBHOOK_SECRET: ${TELEGRAM_WEBHOOK_SECRET}"
  fi
  if printf '%s' "${TELEGRAM_WEBHOOK_SECRET}" | grep -Eq '^[A-Za-z0-9_-]{1,256}$'; then
    break
  fi
  echo "  Rejected: Telegram secret_token allows only A-Z a-z 0-9 _ and - (1-256 characters)."
  read -rsp "  Paste a different value, or press Enter to auto-generate: " TELEGRAM_WEBHOOK_SECRET; echo
done
echo

# ------------------------------------------------------- secret manager ----
# printf '%s' keeps the payload UTF-8 with no trailing newline. Writing a secret
# with a UTF-16/BOM payload makes Cloud Run abort at startup with
# "Secret ... contains non-UTF8 data", so never use `echo > file` here.
write_secret() {
  local name="$1"
  local value="$2"

  if gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" \
      --data-file=- --project "${PROJECT_ID}" >/dev/null
    info "Added new version to ${name}."
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" \
      --data-file=- --replication-policy=automatic --project "${PROJECT_ID}" >/dev/null
    info "Created ${name}."
  fi
}

# ------------------------------------------------------- runtime access ----
RUNTIME_SA="$(gcloud run services describe "${SERVICE}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
if [ -z "${RUNTIME_SA}" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi
info "Cloud Run runtime service account: ${RUNTIME_SA}"

grant_access() {
  local name="$1"
  gcloud secrets add-iam-policy-binding "${name}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project "${PROJECT_ID}" >/dev/null
  info "Granted secretAccessor on ${name}."
}

# ------------------------------------------------------------- apply ----
write_secret TELEGRAM_BOT_TOKEN "${TELEGRAM_BOT_TOKEN}"
write_secret TELEGRAM_ALLOWED_CHAT_ID "${TELEGRAM_ALLOWED_CHAT_ID}"
write_secret TELEGRAM_WEBHOOK_SECRET "${TELEGRAM_WEBHOOK_SECRET}"

for name in "${SECRET_NAMES[@]}"; do
  grant_access "${name}"
done

# gcloud secrets describe succeeds even for a secret with zero versions; make
# sure a usable version exists before binding it, otherwise the deploy fails.
for name in "${SECRET_NAMES[@]}"; do
  gcloud secrets versions describe latest --secret "${name}" \
    --project "${PROJECT_ID}" >/dev/null 2>&1 \
    || die "${name} has no 'latest' version."
done

# --update-secrets merges with the existing bindings, so DATABASE_URL,
# SECRET_KEY and COOKIE_SECRET stay attached.
SECRET_SPEC=""
for name in "${SECRET_NAMES[@]}"; do
  SECRET_SPEC="${SECRET_SPEC:+${SECRET_SPEC},}${name}=${name}:latest"
done

info "Binding secrets to Cloud Run: ${SECRET_SPEC}"
gcloud run services update "${SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --update-secrets="${SECRET_SPEC}" \
  --quiet >/dev/null
info "Cloud Run service updated."

# ---------------------------------------------------- webhook + checks ----
SERVICE_URL="$(gcloud run services describe "${SERVICE}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --format='value(status.url)')"
[ -n "${SERVICE_URL}" ] || die "Could not resolve the Cloud Run service URL."
WEBHOOK_URL="${SERVICE_URL}/telegram/webhook"
info "Webhook URL: ${WEBHOOK_URL}"
echo

info "Health check:"
curl -sS -o /dev/null -w '  HTTP %{http_code}\n' "${SERVICE_URL}/health" \
  || die "Health endpoint is unreachable."

# Telegram stores the secret_token and sends it back as the
# X-Telegram-Bot-Api-Secret-Token header on every delivery; app.py compares it
# with hmac.compare_digest and rejects mismatches with 403.
info "Registering webhook with Telegram:"
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${WEBHOOK_URL}" \
  --data-urlencode "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
  --data-urlencode "allowed_updates=[\"message\",\"edited_message\"]" \
  -w '\n  HTTP %{http_code}\n'
echo

info "Telegram getWebhookInfo:"
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" \
  -w '\n  HTTP %{http_code}\n'
echo
echo "Done. Now send this from the allowed chat to the bot:"
echo "  BUDGET|Marketing|2026|09|25000"
