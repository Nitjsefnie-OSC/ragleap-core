#!/usr/bin/env bash
set -euo pipefail
out=$(mktemp -d)
check() { # package, text that must appear in the wheel listing
  (cd "packages/$1" && pip wheel . --no-deps -q -w "$out/$1" 2>/dev/null)
  listing=$(unzip -l "$out/$1"/*.whl)
  if grep -q "$2" <<< "$listing"; then echo "ok: $1 has $2"
  else echo "FAIL: $1 wheel is missing $2"; exit 1; fi
}
check ragleap-ops "helm/ragleap-ops/Chart.yaml"
check ragleap-app-chart "helm/ragleap-app-chart/Chart.yaml"
check ragleap-observability "helm/ragleap-observability/Chart.yaml"
check ragleap-terraform "modules/"
check ragleap-ansible "playbooks/"
