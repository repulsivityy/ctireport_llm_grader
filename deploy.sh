#!/usr/bin/env bash
# ==============================================================================
# Deploy CTI Report Grader to Google Cloud Run with Secret Manager & Firestore
# ==============================================================================

set -euo pipefail

# 1. Load variables from .env if present
if [ -f .env ]; then
  # Export non-comment lines
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

echo "======================================================"
echo "🛡️ Deploying CTI Report Grader (Cloud Run + Secrets)"
echo "======================================================"
echo "Project ID           : ${PROJECT_ID}"
echo "Region               : ${REGION}"
echo "Service Name         : ${SERVICE_NAME}"
echo "Firestore Collection : ${FIRESTORE_COLLECTION}"
echo "Secret Name          : ${SECRET_NAME}"
echo "Level 1 Model        : ${PRIMARY_MODEL}"
echo "Final Evaluator      : ${META_MODEL}"
echo "Instructor Emails    : ${INSTRUCTOR_EMAILS}"
echo "======================================================"

if [ -z "${PROJECT_ID}" ]; then
  echo "❌ Error: Google Cloud Project ID is not set."
  echo "Run: gcloud config set project <YOUR_PROJECT_ID>"
  exit 1
fi

# Set active project
echo "⚙️ Setting active gcloud project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}"

# Enable required Google Cloud APIs
echo "🔧 Enabling Required Google Cloud APIs..."
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project="${PROJECT_ID}"

# Get project number to configure Cloud Run service account permissions
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
CLOUD_RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Manage Secret Manager for GEMINI_API_KEY
echo "🔒 Synchronizing Google Secret Manager for '${SECRET_NAME}'..."
if ! gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  if [ -n "${GEMINI_API_KEY:-}" ]; then
    echo "Creating new secret '${SECRET_NAME}' in Secret Manager..."
    echo -n "${GEMINI_API_KEY}" | tr -d '\r\n' | gcloud secrets create "${SECRET_NAME}" \
      --data-file=- \
      --replication-policy="automatic" \
      --project="${PROJECT_ID}"
  else
    echo "⚠️ Warning: Secret '${SECRET_NAME}' not found in Secret Manager and GEMINI_API_KEY not in .env."
  fi
else
  if [ -n "${GEMINI_API_KEY:-}" ]; then
    echo "Updating secret '${SECRET_NAME}' with latest key from .env..."
    echo -n "${GEMINI_API_KEY}" | tr -d '\r\n' | gcloud secrets versions add "${SECRET_NAME}" \
      --data-file=- \
      --project="${PROJECT_ID}"
  else
    echo "✅ Secret '${SECRET_NAME}' already exists in Secret Manager."
  fi
fi

# Grant Cloud Run service account access to Secret Manager
echo "🔑 Granting Cloud Run Service Account (${CLOUD_RUN_SA}) Secret Accessor role..."
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${CLOUD_RUN_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}" >/dev/null

# Grant Cloud Run service account access to Firestore (datastore.user)
echo "📦 Granting Cloud Run Service Account (${CLOUD_RUN_SA}) Firestore User role..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CLOUD_RUN_SA}" \
  --role="roles/datastore.user" \
  --condition=None >/dev/null

# Build & Deploy to Cloud Run mounting the Secret
echo "🚀 Building container and deploying to Cloud Run (${REGION})..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --set-env-vars="^##^GOOGLE_CLOUD_PROJECT=${PROJECT_ID}##FIRESTORE_COLLECTION=${FIRESTORE_COLLECTION}##PRIMARY_MODEL=${PRIMARY_MODEL}##META_MODEL=${META_MODEL}##INSTRUCTOR_EMAILS=${INSTRUCTOR_EMAILS}" \
  --set-secrets="GEMINI_API_KEY=${SECRET_NAME}:latest"

echo "======================================================"
echo "🎉 Deployment Complete!"
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --platform managed --region "${REGION}" --project "${PROJECT_ID}" --format 'value(status.url)')
echo "🌐 Live Application URL : ${SERVICE_URL}"
echo "📦 Firestore Collection : ${FIRESTORE_COLLECTION}"
echo "🔒 Secret Mounted       : ${SECRET_NAME} -> GEMINI_API_KEY"
echo "🤖 Level 1 Model        : ${PRIMARY_MODEL}"
echo "🤖 Final Evaluator      : ${META_MODEL}"
echo "👨‍🏫 Authorized Instructors: ${INSTRUCTOR_EMAILS}"
echo "======================================================"
