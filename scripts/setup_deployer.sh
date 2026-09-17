#!/usr/bin/env bash
#
# Create the GitHub Actions deployer identity for ai-registration-engine.
#
# Usage:
#   bash scripts/setup_deployer.sh
#
# Every "Deploy to Google Cloud Run" workflow run so far has failed at the
# "Authenticate to Google Cloud" step because the GCP_SERVICE_ACCOUNT_KEY
# repository secret is missing or points at a revoked key. This script creates a
# dedicated deployer service account, grants it the roles the workflow needs,
# and prints the JSON key to paste into that repository secret.
#
# The key is written to a local file with 0600 permissions. Delete it once it is
# stored in GitHub.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-aiex-registration}"
SA_NAME="${SA_NAME:-github-deployer}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KEY_FILE="${KEY_FILE:-./${SA_NAME}-key.json}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "--> $*"; }

command -v gcloud >/dev/null 2>&1 || die "gcloud is not installed."

gcloud auth print-access-token >/dev/null 2>&1 \
  || die "No usable gcloud credentials. Run: gcloud auth login"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
info "Project: ${PROJECT_ID} (number ${PROJECT_NUMBER})"

# --------------------------------------------------------- service account ----
if gcloud iam service-accounts describe "${SA_EMAIL}" \
     --project "${PROJECT_ID}" >/dev/null 2>&1; then
  info "Service account ${SA_EMAIL} already exists."
else
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="GitHub Actions deployer" \
    --project "${PROJECT_ID}" >/dev/null
  info "Created service account ${SA_EMAIL}."
fi

# ------------------------------------------------------------- deploy roles ----
# cloudbuild.builds.editor + artifactregistry.writer: submit the build and push
#   the image.
# run.admin + iam.serviceAccountUser: create revisions and act as the runtime SA.
# secretmanager.admin: create secrets, add versions, and bind the runtime SA.
for ROLE in \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/run.admin \
  roles/iam.serviceAccountUser \
  roles/secretmanager.admin \
  roles/serviceusage.serviceUsageViewer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet >/dev/null
  info "Granted ${ROLE}."
done

# The Cloud Build service account is a *different* identity from the deployer,
# and it needs writer access on the Artifact Registry repository to push the
# image produced by `gcloud builds submit`.
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CLOUDBUILD_SA}" \
  --role="roles/artifactregistry.writer" \
  --condition=None \
  --quiet >/dev/null
info "Granted artifactregistry.writer to ${CLOUDBUILD_SA}."

# --------------------------------------------------------------- APIs ----
for API in run.googleapis.com cloudbuild.googleapis.com \
           artifactregistry.googleapis.com secretmanager.googleapis.com; do
  gcloud services enable "${API}" --project "${PROJECT_ID}" --quiet
  info "Enabled ${API}."
done

# ----------------------------------------------------------- access key ----
if [ -f "${KEY_FILE}" ]; then
  die "${KEY_FILE} already exists. Move or delete it first."
fi
gcloud iam service-accounts keys create "${KEY_FILE}" \
  --iam-account="${SA_EMAIL}" \
  --project "${PROJECT_ID}" >/dev/null
chmod 600 "${KEY_FILE}" 2>/dev/null || true
info "Wrote service account key to ${KEY_FILE}"

cat <<EOF

========================================================================
Next steps
========================================================================
1. Add these GitHub repository secrets
   (Settings -> Secrets and variables -> Actions -> New repository secret):

     GCP_SERVICE_ACCOUNT_KEY   <- paste the entire contents of ${KEY_FILE}
     GCP_PROJECT_ID            <- ${PROJECT_ID}
     GCP_REGION                <- europe-west1
     GCP_ARTIFACT_REPOSITORY   <- your Artifact Registry repo name
     GCP_CLOUD_RUN_SERVICE     <- ai-registration-engine

   With the GitHub CLI:

     gh secret set GCP_SERVICE_ACCOUNT_KEY --repo rummii/ai-registration-engine < ${KEY_FILE}
     gh secret set GCP_PROJECT_ID          --repo rummii/ai-registration-engine --body '${PROJECT_ID}'
     gh secret set GCP_REGION              --repo rummii/ai-registration-engine --body 'europe-west1'
     gh secret set GCP_ARTIFACT_REPOSITORY --repo rummii/ai-registration-engine --body '<repo-name>'
     gh secret set GCP_CLOUD_RUN_SERVICE   --repo rummii/ai-registration-engine --body 'ai-registration-engine'

2. Delete the key file once the secret is stored:

     rm -f ${KEY_FILE}

3. Re-run the workflow:

     gh workflow run deploy.yml --repo rummii/ai-registration-engine

========================================================================
EOF
