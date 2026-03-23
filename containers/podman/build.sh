#!/usr/bin/env bash
# Build all APME images with Podman. Run from repo root.
# Builds a shared base image first so pip dependencies are resolved once.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "==> Building base image (shared dependencies)..."
podman build -t localhost/apme-base:latest -f containers/base/Dockerfile .

echo "==> Building service images..."
podman build -t apme-primary:latest -f containers/primary/Dockerfile .
podman build -t apme-native:latest -f containers/native/Dockerfile .
podman build -t apme-opa:latest -f containers/opa/Dockerfile .
podman build -t apme-ansible:latest -f containers/ansible/Dockerfile .
podman build -t apme-gitleaks:latest -f containers/gitleaks/Dockerfile .
podman build -t apme-galaxy-proxy:latest -f containers/galaxy-proxy/Dockerfile .
podman build -t apme-gateway:latest -f containers/gateway/Dockerfile .
podman build -t apme-cli:latest -f containers/cli/Dockerfile .
podman build -t apme-ui:latest -f containers/ui/Dockerfile .

echo "Images built."
if [[ -t 0 ]]; then
  read -rp "Start the pod now? [Y/n] " answer
  if [[ "${answer:-Y}" =~ ^[Yy]$ ]]; then
    exec "$ROOT/containers/podman/up.sh"
  fi
fi
