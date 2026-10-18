#!/usr/bin/env bash
# Digest-based promotion: staging -> canary -> production, or rollback to a previous digest.
# The hosting target is configured per deployment (DEPLOY_ENDPOINT); this script refuses to run without it.
set -euo pipefail
stage="${1:?stage}"; api_digest="${2:?image digest}"; runner_digest="${3:-}"
: "${DEPLOY_ENDPOINT:?DEPLOY_ENDPOINT is not configured for this environment}"
: "${DEPLOY_TOKEN:?DEPLOY_TOKEN is not configured}"
case "$api_digest" in sha256:*) ;; *) echo "refusing a non-digest reference: $api_digest" >&2; exit 2;; esac
echo "promoting api@${api_digest} runner@${runner_digest:-unchanged} to ${stage}"
curl --fail --silent --show-error -X POST "${DEPLOY_ENDPOINT}/deployments" \
  -H "Authorization: Bearer ${DEPLOY_TOKEN}" -H "Content-Type: application/json" \
  -d "{\"stage\":\"${stage}\",\"api_digest\":\"${api_digest}\",\"runner_digest\":\"${runner_digest}\",\"migrations\":\"expand-then-contract\"}"
