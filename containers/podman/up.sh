#!/usr/bin/env bash
# Start the APME pod (Primary, Ansible, OPA, Cache maintainer). Run from repo root.
# CLI is not part of the pod; use run-cli.sh to run a scan with CWD mounted.
#
# Override the cache host path:
#   APME_CACHE_HOST_PATH=/my/cache ./up.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CACHE_PATH="${APME_CACHE_HOST_PATH:-/tmp/apme-cache}"

if [[ "$CACHE_PATH" != /* ]]; then
    echo "ERROR: APME_CACHE_HOST_PATH must be an absolute path (got: $CACHE_PATH)" >&2
    exit 1
fi

mkdir -p "$CACHE_PATH"

if [ "$CACHE_PATH" != "/tmp/apme-cache" ]; then
    ESCAPED_PATH=$(printf '%s\n' "$CACHE_PATH" | sed 's/[&/\]/\\&/g')
    sed "s|path: /tmp/apme-cache|path: ${ESCAPED_PATH}|" containers/podman/pod.yaml \
        | podman play kube -
else
    podman play kube containers/podman/pod.yaml
fi

echo "Pod apme-pod started (cache: $CACHE_PATH). Run a scan: containers/podman/run-cli.sh"
