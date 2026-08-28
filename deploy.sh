#!/usr/bin/env bash
# ==============================================================================
# CTI Report Grader - deploy / purge helper
#
#   ./deploy.sh            Build & deploy to Cloud Run behind Identity-Aware Proxy
#   ./deploy.sh purge      PERMANENTLY delete all stored submissions (Firestore + local)
#   ./deploy.sh iap-access Re-grant IAP access to ALLOWED_PRINCIPALS only
# ==============================================================================

set -euo pipefail

MODE="${1:-deploy}"

# ------------------------------------------------------------------ env / config
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

SERVICE_NAME="${SERVICE_NAME:-cti-report-grader}"
REGION="${REGION:-asia-southeast1}"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo '')}"
FIRESTORE_COLLECTION="${FIRESTORE_COLLECTION:-cti_submissions}"
SECRET_NAME="${SECRET_NAME:-GEMINI_API_KEY}"
INSTRUCTOR_EMAILS="${INSTRUCTOR_EMAILS:-}"
PRIMARY_MODEL="${PRIMARY_MODEL:-gemini-3.5-flash-lite}"
META_MODEL="${META_MODEL:-gemini-3.7-flash}"
ALLOWED_PRINCIPALS="${ALLOWED_PRINCIPALS:-}"

if [ -z "${PROJECT_ID}" ]; then
  echo "❌ Google Cloud Project ID is not set. Run: gcloud config set project <ID>"
  exit 1
fi
gcloud config set project "${PROJECT_ID}" >/dev/null

grant_iap_access() {
  if [ -z "${ALLOWED_PRINCIPALS}" ]; then
    echo "⚠️  ALLOWED_PRINCIPALS not set - grant IAP access manually, e.g.:"
    echo "    gcloud iap web add-iam-policy-binding --project=${PROJECT_ID} --resource-type=cloud-run --service=${SERVICE_NAME} --region=${REGION} \\"
    echo "      --member='user:student@example.com' --role='roles/iap.httpsResourceAccessor'"
    return
  fi
  echo "🔐 Granting roles/iap.httpsResourceAccessor on Cloud Run IAP resource (${SERVICE_NAME}): ${ALLOWED_PRINCIPALS}"
  IFS=',' read -ra _PRINCIPALS <<< "${ALLOWED_PRINCIPALS}"
  for principal in "${_PRINCIPALS[@]}"; do
    p="$(echo "${principal}" | xargs)"
    if [ -z "${p}" ] || [ "${p}" = "user:" ] || [ "${p}" = "group:" ] || [ "${p}" = "domain:" ]; then
      continue
    fi
    echo "   -> Granting to: ${p}"
    gcloud iap web add-iam-policy-binding \
      --project="${PROJECT_ID}" \
      --resource-type=cloud-run \
      --service="${SERVICE_NAME}" \
      --region="${REGION}" \
      --member="${p}" \
      --role="roles/iap.httpsResourceAccessor" >/dev/null
  done
}

# ==============================================================================
# PURGE - delete all stored submissions
# ==============================================================================
if [ "${MODE}" = "purge" ]; then
  echo "======================================================"
  echo "⚠️  PURGE - this permanently deletes ALL student submissions"
  echo "   Project    : ${PROJECT_ID}"
  echo "   Firestore  : collection '${FIRESTORE_COLLECTION}'"
  echo "   Local file : ./submissions.db (if present)"
  echo "======================================================"
  read -r -p "Type the collection name ('${FIRESTORE_COLLECTION}') to confirm: " CONFIRM
  if [ "${CONFIRM}" != "${FIRESTORE_COLLECTION}" ]; then
    echo "Aborted."
    exit 1
  fi

  echo "🔥 Deleting Firestore collection '${FIRESTORE_COLLECTION}'..."
  gcloud firestore bulk-delete \
    --collection-ids="${FIRESTORE_COLLECTION}" \
    --project="${PROJECT_ID}" \
    --quiet

  if [ -f submissions.db ]; then
    rm -f submissions.db
    echo "🧹 Removed local submissions.db"
  fi

  echo "✅ Purge complete. (A running Cloud Run instance may hold a stale in-memory"
  echo "   Firestore client cache; redeploy or wait for it to recycle if needed.)"
  exit 0
fi

# ==============================================================================
# IAP-ACCESS - re-grant access without redeploying
# ==============================================================================
if [ "${MODE}" = "iap-access" ]; then
  grant_iap_access
  exit 0
fi

# ==============================================================================
# DEPLOY
# ==============================================================================
echo "======================================================"
echo "🛡️  Deploying CTI Report Grader (Cloud Run + IAP)"
echo "   Project / Region : ${PROJECT_ID} / ${REGION}"
echo "   Service          : ${SERVICE_NAME}"
echo "   Firestore        : ${FIRESTORE_COLLECTION}"
echo "   Models           : ${PRIMARY_MODEL}  |  ${META_MODEL}"
echo "   Instructors      : ${INSTRUCTOR_EMAILS}"
echo "======================================================"

echo "🔧 Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iap.googleapis.com \
  --project="${PROJECT_ID}"

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
CLOUD_RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# --- Secret Manager: GEMINI_API_KEY ------------------------------------------
echo "🔒 Synchronising Secret Manager '${SECRET_NAME}'..."
if ! gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  if [ -n "${GEMINI_API_KEY:-}" ]; then
    printf '%s' "${GEMINI_API_KEY}" | tr -d '\r\n' | gcloud secrets create "${SECRET_NAME}" \
      --data-file=- --replication-policy="automatic" --project="${PROJECT_ID}"
  else
    echo "⚠️  Secret '${SECRET_NAME}' missing and GEMINI_API_KEY not in .env."
  fi
elif [ -n "${GEMINI_API_KEY:-}" ]; then
  printf '%s' "${GEMINI_API_KEY}" | tr -d '\r\n' | gcloud secrets versions add "${SECRET_NAME}" \
    --data-file=- --project="${PROJECT_ID}"
fi

gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${CLOUD_RUN_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}" >/dev/null

# --- Firestore access for the runtime SA ------------------------------------
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CLOUD_RUN_SA}" \
  --role="roles/datastore.user" \
  --condition=None >/dev/null

# --- IAP service identity ---------------------------------------------------
echo "🪪 Ensuring the IAP service identity exists..."
gcloud beta services identity create --service=iap.googleapis.com --project="${PROJECT_ID}" >/dev/null 2>&1 || true

GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"
REDIRECT_URI="${REDIRECT_URI:-}"

# --- Build & deploy (Public landing page with Google Sign-In) --------------
echo "🚀 Building and deploying with public landing page & Google OAuth..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --set-env-vars="^##^GOOGLE_CLOUD_PROJECT=${PROJECT_ID}##FIRESTORE_COLLECTION=${FIRESTORE_COLLECTION}##PRIMARY_MODEL=${PRIMARY_MODEL}##META_MODEL=${META_MODEL}##INSTRUCTOR_EMAILS=${INSTRUCTOR_EMAILS}##GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}##GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}##REDIRECT_URI=${REDIRECT_URI}" \
  --set-secrets="GEMINI_API_KEY=${SECRET_NAME}:latest"

grant_iap_access

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --platform managed --region "${REGION}" --project "${PROJECT_ID}" --format 'value(status.url)')

echo "======================================================"
echo "🎉 Deployment complete"
echo "🌐 URL        : ${SERVICE_URL}"
echo "🔒 Access     : Public landing page + Google OAuth (Google / Gmail sign-in)"
echo "👨‍🏫 Instructors: ${INSTRUCTOR_EMAILS}"
echo "                (must match the user's Google email to view Gradebook)"
echo
echo "Follow-ups you may still need to do once, in the console:"
echo "  • Configure the OAuth consent screen if this project has never used IAP."
echo "  • (Optional hardening) verify the signed IAP JWT instead of trusting the"
echo "    identity header: set IAP_JWT_AUDIENCE (see"
echo "    https://cloud.google.com/iap/docs/signed-headers-howto) and redeploy."
echo "======================================================"
