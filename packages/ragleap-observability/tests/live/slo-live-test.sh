#!/usr/bin/env bash
# Live test of the ragleap-observability SLO rules on a REAL Prometheus (one container, no Kubernetes).
# Uses the rules from origin/main , a stand-in target, and removes everything it creates.
# Takes roughly 20-25 minutes. Run it with nohup so an SSH drop cannot stop it:
#   nohup bash ~/slo-live-test.sh > ~/slo-live-test.log 2>&1 &
set -euo pipefail

IMG=prom/prometheus:v3.13.4
NET=rl-slo-net
PROM=rl-slo-prom
TGT=rl-slo-target
PORT=19091
LOG=$HOME/slo-live-test-result.txt
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

stop() { echo "STOP: $*"; exit 1; }

echo "== preflight"
for c in docker helm git curl python3 awk; do command -v "$c" >/dev/null || stop "$c not found"; done
docker image inspect "$IMG" >/dev/null 2>&1 || stop "$IMG is not on disk (this script never pulls images)"
NAMES=$(docker ps -a --format '{{.Names}}')
if grep -q -x -e "$PROM" -e "$TGT" <<< "$NAMES"; then stop "container $PROM or $TGT already exists"; fi
NETS=$(docker network ls --format '{{.Name}}')
if grep -q -x -e "$NET" <<< "$NETS"; then stop "network $NET already exists"; fi
FREE=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
[ "$FREE" -ge 3 ] || stop "only ${FREE}G free on /, need at least 3G"
MEM=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
[ "$MEM" -ge 600 ] || stop "only ${MEM}M memory available, need at least 600M"
if (echo > /dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then stop "port $PORT is in use"; fi
echo "free disk ${FREE}G, available memory ${MEM}M, image present, names and port free"

W=$(mktemp -d /tmp/rl-slo-live.XXXXXX)
cleanup() {
  docker rm -f "$PROM" "$TGT" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$W"
  echo "cleanup done (containers, network and temp files removed; images untouched)"
}
trap cleanup EXIT

echo "== rendering the rules from origin/main"
cd "$HOME/ragleap-core"
git fetch origin -q
git archive origin/main packages/ragleap-observability/helm | tar -x -C "$W"
CH=$W/packages/ragleap-observability/helm/ragleap-observability
echo "chart under test: $(sed -n 's/^version: //p' "$CH/Chart.yaml")"
mkdir "$W/cfg"
helm template t "$CH" --set slo.enabled=true -s templates/prometheus-rules-configmap.yaml \
  | awk '/^  alerts.yml: \|/{f=1;next} f&&/^    /{sub(/^    /,"");print;next} f{exit}' > "$W/cfg/alerts.yml"
NRULES=$(grep -c 'alert:' "$W/cfg/alerts.yml" || true)
[ "$NRULES" = "4" ] || stop "expected 4 alert rules, found $NRULES"

write_cfg() { # $1 = targets list in YAML flow style
  cat > "$W/cfg/prometheus.yml" <<EOF
global:
  scrape_interval: 15s
  evaluation_interval: 15s
rule_files:
  - /etc/prom/alerts.yml
scrape_configs:
  - job_name: 'ragleap-postgres'
    static_configs:
      - targets: $1
EOF
  chmod -R a+rX "$W/cfg"
}
write_cfg "['$TGT:9090']"

api() { curl -s "http://127.0.0.1:$PORT$1"; }
astate() { # alertname -> firing | pending | inactive
  api /api/v1/alerts | python3 -c "
import sys, json
n = sys.argv[1]
al = [a['state'] for a in json.load(sys.stdin)['data']['alerts'] if a['labels'].get('alertname') == n]
print('firing' if 'firing' in al else ('pending' if 'pending' in al else 'inactive'))
" "$1"
}

FAILS=0
RESULTS=()
expect() { # name want timeout label
  local name=$1 want=$2 timeout=$3 label=$4 start=$SECONDS s="?"
  while [ $((SECONDS - start)) -le "$timeout" ]; do
    s=$(astate "$name" 2>/dev/null || echo "?")
    if [ "$s" = "$want" ]; then
      RESULTS+=("PASS  $label (after $((SECONDS - start))s)"); echo "PASS  $label (after $((SECONDS - start))s)"; return 0
    fi
    sleep 10
  done
  FAILS=$((FAILS + 1))
  RESULTS+=("FAIL  $label (still '$s' after ${timeout}s)"); echo "FAIL  $label (still '$s' after ${timeout}s)"
}
expect_now() { # name want label
  local s; s=$(astate "$1" 2>/dev/null || echo "?")
  if [ "$s" = "$2" ]; then RESULTS+=("PASS  $3"); echo "PASS  $3"
  else FAILS=$((FAILS + 1)); RESULTS+=("FAIL  $3 (got '$s')"); echo "FAIL  $3 (got '$s')"; fi
}

echo "== starting stand-in target and Prometheus ($(date +%T))"
docker network create "$NET" >/dev/null
docker run -d --name "$TGT" --network "$NET" --memory 128m "$IMG" >/dev/null
docker run -d --name "$PROM" --network "$NET" --memory 256m -p 127.0.0.1:$PORT:9090 \
  -v "$W/cfg":/etc/prom:ro "$IMG" \
  --config.file=/etc/prom/prometheus.yml --web.enable-lifecycle --storage.tsdb.retention.time=1h >/dev/null

READY=""
for i in $(seq 1 12); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/-/ready" || true)
  [ "$CODE" = "200" ] && { READY=yes; break; }
  sleep 5
done
[ "$READY" = "yes" ] || stop "Prometheus did not become ready"

echo "== waiting 45s for the first rule evaluations"
sleep 45
echo "== rules loaded?"
api /api/v1/rules | python3 -c "
import sys, json
rules = [r for g in json.load(sys.stdin)['data']['groups'] for r in g['rules']]
print(len(rules), 'rules,', 'health:', sorted({r['health'] for r in rules}))
sys.exit(0 if len(rules) == 4 and all(r['health'] == 'ok' for r in rules) else 1)
" || stop "rules did not load healthy"

echo "== phase 1: healthy target for 2 minutes (negative control) ($(date +%T))"
sleep 120
for a in PostgresExporterDown RagleapAvailabilityFastBurn RagleapAvailabilitySlowBurn RagleapTargetAbsent; do
  expect_now "$a" inactive "healthy: $a is not firing"
done

echo "== phase 2: stop the target ($(date +%T))"
docker stop "$TGT" >/dev/null
expect RagleapAvailabilityFastBurn firing 600 "outage: RagleapAvailabilityFastBurn fires"
expect PostgresExporterDown firing 600 "outage: PostgresExporterDown fires"
expect_now RagleapTargetAbsent inactive "outage: RagleapTargetAbsent stays quiet (the up series still exists, value 0)"

echo "== phase 3: start the target again ($(date +%T))"
docker start "$TGT" >/dev/null
expect PostgresExporterDown inactive 180 "recovery: PostgresExporterDown clears"
expect RagleapAvailabilityFastBurn inactive 600 "recovery: RagleapAvailabilityFastBurn clears"

echo "== phase 4: remove the target from the scrape config and reload ($(date +%T))"
write_cfg "[]"
curl -s -X POST "http://127.0.0.1:$PORT/-/reload" >/dev/null
expect RagleapTargetAbsent firing 540 "vanished target: RagleapTargetAbsent fires"
S=$(astate PostgresExporterDown 2>/dev/null || echo "?")
echo "OBSERVED  vanished target: PostgresExporterDown is '$S' (an up==0 rule cannot see a missing series)"
RESULTS+=("OBSERVED  vanished target: PostgresExporterDown is '$S'")

echo "== phase 5: put the target back ($(date +%T))"
write_cfg "['$TGT:9090']"
curl -s -X POST "http://127.0.0.1:$PORT/-/reload" >/dev/null
expect RagleapTargetAbsent inactive 240 "restored: RagleapTargetAbsent clears"

echo
echo "== SUMMARY ($(date +%T))"
for r in "${RESULTS[@]}"; do echo "$r"; done
echo "Not exercised: RagleapAvailabilitySlowBurn firing (needs a 15 minute outage), AlertManager delivery, Kubernetes wiring."
echo "Scrape interval was 15s here (chart default is 30s). The Prometheus had little history, so the burn-rate windows averaged only the data that existed."
if [ "$FAILS" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "$FAILS CHECK(S) FAILED"; exit 1; fi
