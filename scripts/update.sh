#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TARGET="${TARGET:-nuc}"
GAME_FILE="${GAME_FILE:-$ROOT/local-roms/game.d64}"
NAMESPACE="${NAMESPACE:-default}"
KUBECTL="${KUBECTL:-kubectl}"
MODE="${1:---dry-run}"

if [[ "$MODE" != "--dry-run" && "$MODE" != "--apply" ]]; then
  echo "Usage: bash scripts/update.sh [--dry-run|--apply]" >&2; exit 2
fi
if [[ "$TARGET" != nuc || "$(uname -m)" != x86_64 ]]; then
  echo "This build targets the x86_64 NUC only" >&2; exit 2
fi
for tool in docker kubectl sha256sum; do command -v "$tool" >/dev/null || {
  echo "Missing required tool: $tool" >&2; exit 2; }
done
if [[ ! -f "$GAME_FILE" ]]; then
  echo "Place a legally obtained D64 at $GAME_FILE (not in Git)" >&2; exit 2
fi
# Fail closed when the local checkout is stale or on the wrong branch.
if ! grep -q 'C64 UI KB2' web/index.html || [[ ! -f web/assets/c64-keyboard.js ]]; then
  echo "This checkout has an OLD frontend. Update branch feat/server-c64-mvp first:" >&2
  echo "  git fetch origin && git switch feat/server-c64-mvp && git pull --ff-only" >&2
  exit 2
fi
echo "Local source: branch=$(git branch --show-current), commit=$(git rev-parse --short HEAD), UI=KB2"
bytes="$(stat -c %s "$GAME_FILE")"
case "$bytes" in 174848|175531|196608) ;; *) echo "Unrecognized D64 size: $bytes" >&2; exit 2;; esac

TAG="local-$(git rev-parse --short=12 HEAD)-$(sha256sum Dockerfile requirements.txt server/*.py web/index.html web/assets/*.css web/assets/*.js | sha256sum | cut -c1-12)"
IMAGE="wizard-of-wor:${TAG}"
TEMP="$(mktemp)"
trap 'rm -f "$TEMP"' EXIT
sed "s@ghcr.io/nicqx/wizard-of-wor:main@${IMAGE}@g" k8s/deployment.yaml > "$TEMP"
echo "Target: $TARGET / namespace: $NAMESPACE"
echo "Image: $IMAGE"
"$KUBECTL" get node nuc >/dev/null
"$KUBECTL" -n "$NAMESPACE" apply --dry-run=client -f "$TEMP" >/dev/null
if [[ "$MODE" == "--dry-run" ]]; then
  echo "DRY-RUN: No image built/imported, no secret changed, no deployment applied."
  exit 0
fi

# Create a protected manifest backup, without fetching or persisting secret data.
STATE="${NICQX_STATE_DIR:-$HOME/.local/state/nicqx-infra}/nuc/wizard-of-wor"
mkdir -p "$STATE"; chmod 700 "$STATE"
BACKUP="$STATE/$(date -u +%Y%m%dT%H%M%SZ)-before.yaml"
umask 077
"$KUBECTL" -n "$NAMESPACE" get deployment/wizard-of-wor service/wizard-of-wor-service \
  -o yaml > "$BACKUP" 2>/dev/null || { rm -f "$BACKUP"; echo "No preexisting deployment to back up."; }
if [[ -f "$BACKUP" ]]; then echo "Previous K8s state: $BACKUP"; fi
docker build -t "$IMAGE" .
docker save "$IMAGE" | sudo k3s ctr -n k8s.io images import -
"$KUBECTL" -n "$NAMESPACE" create secret generic wizard-of-wor-game \
  --from-file="game.d64=$GAME_FILE" --dry-run=client -o yaml | "$KUBECTL" -n "$NAMESPACE" apply -f -
"$KUBECTL" -n "$NAMESPACE" apply -f "$TEMP"
"$KUBECTL" -n "$NAMESPACE" rollout status deployment/wizard-of-wor --timeout=180s
"$KUBECTL" -n "$NAMESPACE" exec deployment/wizard-of-wor -c wizard -- \
  python -c 'from server.app import UI_VERSION; from pathlib import Path; assert UI_VERSION == "KB2"; assert "Billentyűzet megnyitása" in Path("/app/web/index.html").read_text(); print("Deployed pod UI: KB2 verified")'
"$KUBECTL" -n "$NAMESPACE" get deploy,svc -l app=wizard-of-wor
echo "Installed and verified (KB2). Ingress and landing page were NOT changed."
