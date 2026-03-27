#!/usr/bin/env bash
# Start the APME pod (Primary, Native, Ansible, OPA, Gitleaks, Galaxy Proxy). Run from repo root.
# CLI is not part of the pod; use run-cli.sh to run a scan with CWD mounted.
#
# Cache host path: default is XDG cache (${XDG_CACHE_HOME:-$HOME/.cache}/apme).
# Override: APME_CACHE_HOST_PATH=/my/cache ./up.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Default: XDG cache dir (persists across reboots); override with APME_CACHE_HOST_PATH
CACHE_PATH="${APME_CACHE_HOST_PATH:-${XDG_CACHE_HOME:-$HOME/.cache}/apme}"

if [[ "$CACHE_PATH" != /* ]]; then
  echo "ERROR: APME_CACHE_HOST_PATH must be an absolute path (got: $CACHE_PATH)" >&2
  exit 1
fi

if [[ "$CACHE_PATH" == *$'\n'* ]]; then
  echo "ERROR: APME_CACHE_HOST_PATH must not contain newlines" >&2
  exit 1
fi

mkdir -p "$CACHE_PATH"

# Load Abbenay secrets (.env) if present.
ABBENAY_ENV="$ROOT/containers/abbenay/.env"
if [[ -f "$ABBENAY_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ABBENAY_ENV"
  set +a
fi
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
APME_AI_MODEL="${APME_AI_MODEL:-}"
APME_FEEDBACK_ENABLED="${APME_FEEDBACK_ENABLED:-true}"
APME_FEEDBACK_GITHUB_REPO="${APME_FEEDBACK_GITHUB_REPO:-}"
APME_FEEDBACK_GITHUB_TOKEN="${APME_FEEDBACK_GITHUB_TOKEN:-}"

# Tear down any existing pod so we get a clean start.
if podman pod exists apme-pod 2>/dev/null; then
  echo "Stopping existing apme-pod..."
  podman pod stop apme-pod 2>/dev/null || true
  podman pod rm apme-pod 2>/dev/null || true
fi

# Pod YAML cannot use env vars; we inject values via envsubst.
# CACHE_PATH is escaped for sed since it may contain special chars;
# everything else goes through envsubst so secrets stay out of argv.
ESCAPED_PATH=$(printf '%s\n' "$CACHE_PATH" | sed -e 's/\\/\\\\/g' -e 's/[&|]/\\&/g')
export OPENROUTER_API_KEY APME_AI_MODEL APME_ROOT="$ROOT"
export APME_FEEDBACK_ENABLED APME_FEEDBACK_GITHUB_REPO APME_FEEDBACK_GITHUB_TOKEN
sed "s|path: __APME_CACHE_PATH__|path: ${ESCAPED_PATH}|" containers/podman/pod.yaml \
  | envsubst '$OPENROUTER_API_KEY $APME_AI_MODEL $APME_ROOT $APME_FEEDBACK_ENABLED $APME_FEEDBACK_GITHUB_REPO $APME_FEEDBACK_GITHUB_TOKEN' \
  | podman play kube -

echo "Pod apme-pod started (cache: $CACHE_PATH). Run a scan: containers/podman/run-cli.sh"

if [[ -n "$APME_FEEDBACK_GITHUB_REPO" && -n "$APME_FEEDBACK_GITHUB_TOKEN" ]]; then
  echo "Issue reporting enabled (repo: $APME_FEEDBACK_GITHUB_REPO)"
else
  echo "Issue reporting disabled. To enable, export APME_FEEDBACK_GITHUB_REPO and APME_FEEDBACK_GITHUB_TOKEN."
fi
