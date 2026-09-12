#!/usr/bin/env bash
# Compare charts/opendesign-mcp with what is running. Exit 0 = in sync, 1 = drift.
#   1. repo vs release : helm template (this repo) <-> helm get manifest
#                        (skipped while the instance is still kubectl-managed)
#   2. cluster vs chart: kubectl diff of the rendered chart against live objects
# Extra arguments are passed to `helm template`.
#   CONTEXT=default RELEASE=od-mcp NAMESPACE=open-design \
#     VALUES=deploy/local/od-mcp.yaml scripts/check-drift.sh
set -euo pipefail

CONTEXT="${CONTEXT:-default}"
RELEASE="${RELEASE:-od-mcp}"
NAMESPACE="${NAMESPACE:-open-design}"
VALUES="${VALUES:-deploy/local/od-mcp.yaml}"
cd "$(dirname "$0")/.."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

helm template "$RELEASE" ./charts/opendesign-mcp -n "$NAMESPACE" --skip-tests \
  -f "$VALUES" "$@" > "$tmp/repo.yaml"

rc=0
if helm --kube-context "$CONTEXT" get manifest "$RELEASE" -n "$NAMESPACE" \
     > "$tmp/release.yaml" 2>/dev/null; then
  # -B: helm get manifest ends with an extra blank line that helm template does not.
  if diff -u -B "$tmp/release.yaml" "$tmp/repo.yaml" > "$tmp/repo.diff"; then
    echo "1. repo == release ${RELEASE}"
  else
    echo "1. DRIFT: this repo renders differently from release ${RELEASE}:"
    cat "$tmp/repo.diff"
    rc=1
  fi
else
  echo "1. skipped: no Helm release ${RELEASE} in ${NAMESPACE} (still kubectl-managed)"
fi

set +e
kubectl --context "$CONTEXT" diff -f "$tmp/repo.yaml" > "$tmp/live.diff" 2>&1
krc=$?
set -e
case "$krc" in
  0) echo "2. cluster == chart (context ${CONTEXT})" ;;
  1) echo "2. DRIFT: live objects differ from the chart:"; cat "$tmp/live.diff"; rc=1 ;;
  *) cat "$tmp/live.diff" >&2; exit "$krc" ;;
esac
exit "$rc"
