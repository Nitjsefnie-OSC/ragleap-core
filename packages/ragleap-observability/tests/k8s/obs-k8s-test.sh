#!/usr/bin/env bash
# Kubernetes test of the ragleap-observability SLO alerts and AlertManager wiring, on a throwaway kind cluster.
# Uses a stand-in Postgres (so the real postgres-exporter runs) and a stand-in Slack-compatible receiver.
# Meant for a GitHub runner (about 35-45 minutes). It refuses to run elsewhere unless FORCE=1,
# because the shared VPS does not have the disk and memory for a kind cluster.
set -euo pipefail

CL=obs-k8s-test
NS=obs-test
REL=obs
HERE=$(cd "$(dirname "$0")" && pwd)
CH=$HERE/../../helm/ragleap-observability
PROM_PORT=19090
AM_PORT=19093
FAILS=0
RESULTS=()
PF_PROM=""
PF_AM=""

stop() { echo "STOP: $*"; exit 1; }

if [ "${GITHUB_ACTIONS:-}" != "true" ] && [ "${FORCE:-}" != "1" ]; then
  stop "not on a GitHub runner. A kind cluster needs several GB of disk and memory. Set FORCE=1 to run anyway."
fi

cleanup() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "== diagnostics (exit code $rc)"
    kubectl -n "$NS" get pods -o wide 2>&1 | tail -20 || true
    kubectl -n "$NS" logs deploy/ragleap-prometheus --tail=40 2>&1 || true
    kubectl -n "$NS" logs deploy/ragleap-alertmanager --tail=40 2>&1 || true
    kubectl -n "$NS" logs deploy/stand-in --tail=30 2>&1 || true
  fi
  kill $(jobs -p) 2>/dev/null || true
  kind delete cluster --name "$CL" >/dev/null 2>&1 || true
  echo "cleanup done (kind cluster $CL deleted)"
}
trap cleanup EXIT

echo "== preflight"
for c in kubectl helm curl python3; do command -v "$c" >/dev/null || stop "$c not found"; done
if ! command -v kind >/dev/null; then
  echo "kind not preinstalled; downloading v0.24.0"
  curl -sLo /tmp/kind https://github.com/kubernetes-sigs/kind/releases/download/v0.24.0/kind-linux-amd64
  chmod +x /tmp/kind
  export PATH=/tmp:$PATH
fi
kind version
CLUSTERS=$(kind get clusters 2>&1 || true)
if grep -q -x -e "$CL" <<< "$CLUSTERS"; then stop "kind cluster $CL already exists"; fi
[ -f "$CH/Chart.yaml" ] || stop "chart not found at $CH"
echo "chart under test: $(sed -n 's/^version: //p' "$CH/Chart.yaml")"

echo "== creating kind cluster $CL"
kind create cluster --name "$CL" --wait 180s
kubectl create namespace "$NS"

echo "== stand-in Postgres, stand-in Slack receiver, Secrets"
kubectl -n "$NS" apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ragleap-db
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ragleap-db
  template:
    metadata:
      labels:
        app: ragleap-db
    spec:
      containers:
        - name: postgres
          image: postgres:16-alpine
          env:
            - name: POSTGRES_PASSWORD
              value: testpw
          ports:
            - containerPort: 5432
---
apiVersion: v1
kind: Service
metadata:
  name: ragleap-db
spec:
  selector:
    app: ragleap-db
  ports:
    - port: 5432
      targetPort: 5432
EOF

cat > /tmp/standin-server.py <<'EOF'
import http.server

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode()
        print("WEBHOOK " + body.replace("\n", " "), flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass

http.server.HTTPServer(("", 8080), H).serve_forever()
EOF
kubectl -n "$NS" create configmap standin-code --from-file=server.py=/tmp/standin-server.py
kubectl -n "$NS" apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: stand-in
spec:
  replicas: 1
  selector:
    matchLabels:
      app: stand-in
  template:
    metadata:
      labels:
        app: stand-in
    spec:
      containers:
        - name: server
          image: python:3.12-alpine
          command: ["python", "-u", "/code/server.py"]
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: code
              mountPath: /code
      volumes:
        - name: code
          configMap:
            name: standin-code
---
apiVersion: v1
kind: Service
metadata:
  name: stand-in
spec:
  selector:
    app: stand-in
  ports:
    - port: 8080
      targetPort: 8080
EOF
kubectl -n "$NS" create secret generic ragleap-db-exporter-secret \
  --from-literal=connection-string='postgresql://postgres:testpw@ragleap-db:5432/postgres?sslmode=disable'
kubectl -n "$NS" create secret generic ragleap-alertmanager-secrets \
  --from-literal=slack_url='http://stand-in:8080/slack'
kubectl -n "$NS" rollout status deploy/ragleap-db --timeout=240s
kubectl -n "$NS" rollout status deploy/stand-in --timeout=240s

echo "== installing the chart (Grafana, Loki, Promtail off; SLO alerts and the Slack receiver on)"
helm install "$REL" "$CH" -n "$NS" \
  --set grafana.enabled=false --set loki.enabled=false --set promtail.enabled=false \
  --set slo.enabled=true --set alertmanager.receivers.slack.enabled=true \
  --wait --timeout 300s
kubectl -n "$NS" get pods

pf() { # service local-port remote-port variable-name
  kubectl -n "$NS" port-forward "svc/$1" "$2:$3" >/dev/null 2>&1 &
  printf -v "$4" '%s' "$!"
  local i
  for i in $(seq 1 30); do
    if curl -s -o /dev/null "http://127.0.0.1:$2/-/ready"; then return 0; fi
    sleep 1
  done
  return 1
}
pf ragleap-prometheus "$PROM_PORT" 9090 PF_PROM || stop "Prometheus port-forward failed"
pf ragleap-alertmanager "$AM_PORT" 9093 PF_AM || stop "AlertManager port-forward failed"

astate() { # alertname -> firing | pending | inactive
  curl -s "http://127.0.0.1:$PROM_PORT/api/v1/alerts" | python3 -c "
import sys, json
n = sys.argv[1]
al = [a['state'] for a in json.load(sys.stdin)['data']['alerts'] if a['labels'].get('alertname') == n]
print('firing' if 'firing' in al else ('pending' if 'pending' in al else 'inactive'))
" "$1"
}
upval() {
  curl -s -G "http://127.0.0.1:$PROM_PORT/api/v1/query" --data-urlencode 'query=up{job="ragleap-postgres"}' | python3 -c "
import sys, json
r = json.load(sys.stdin)['data']['result']
print(r[0]['value'][1] if r else 'none')
"
}
record() { RESULTS+=("$1"); echo "$1"; }
expect() { # name want timeout label
  local name=$1 want=$2 timeout=$3 label=$4 start=$SECONDS s="?"
  while [ $((SECONDS - start)) -le "$timeout" ]; do
    s=$(astate "$name" 2>/dev/null || echo "?")
    if [ "$s" = "$want" ]; then record "PASS  $label (after $((SECONDS - start))s)"; return 0; fi
    sleep 10
  done
  FAILS=$((FAILS + 1)); record "FAIL  $label (still '$s' after ${timeout}s)"
}
expect_now() { # name want label
  local s; s=$(astate "$1" 2>/dev/null || echo "?")
  if [ "$s" = "$2" ]; then record "PASS  $3"; else FAILS=$((FAILS + 1)); record "FAIL  $3 (got '$s')"; fi
}
expect_webhook() { # extended-regex timeout label
  local pat=$1 timeout=$2 label=$3 start=$SECONDS L=""
  while [ $((SECONDS - start)) -le "$timeout" ]; do
    L=$(kubectl -n "$NS" logs deploy/stand-in 2>/dev/null || true)
    if grep -q -E -- "$pat" <<< "$L"; then record "PASS  $label (after $((SECONDS - start))s)"; return 0; fi
    sleep 10
  done
  FAILS=$((FAILS + 1)); record "FAIL  $label (not seen in the receiver after ${timeout}s)"
}

echo "== phase 0: wiring ($(date +%T))"
sleep 45
curl -s "http://127.0.0.1:$PROM_PORT/api/v1/rules" | python3 -c "
import sys, json
rules = [r for g in json.load(sys.stdin)['data']['groups'] for r in g['rules']]
print(len(rules), 'rules, health:', sorted({r['health'] for r in rules}))
sys.exit(0 if len(rules) == 4 and all(r['health'] == 'ok' for r in rules) else 1)
" && record "PASS  4 rules loaded and healthy" || { FAILS=$((FAILS + 1)); record "FAIL  rules not loaded healthy"; }
curl -s "http://127.0.0.1:$PROM_PORT/api/v1/alertmanagers" | python3 -c "
import sys, json
n = len(json.load(sys.stdin)['data']['activeAlertmanagers'])
print(n, 'active AlertManager(s)')
sys.exit(0 if n >= 1 else 1)
" && record "PASS  Prometheus has an active AlertManager" || { FAILS=$((FAILS + 1)); record "FAIL  no active AlertManager"; }
START=$SECONDS
while [ "$(upval 2>/dev/null || echo ?)" != "1" ] && [ $((SECONDS - START)) -le 180 ]; do sleep 10; done
if [ "$(upval 2>/dev/null || echo ?)" = "1" ]; then record "PASS  exporter target is up"; else FAILS=$((FAILS + 1)); record "FAIL  exporter target is not up"; fi

echo "== phase 1: healthy for 2 minutes (negative control) ($(date +%T))"
sleep 120
for a in PostgresExporterDown RagleapAvailabilityFastBurn RagleapAvailabilitySlowBurn RagleapTargetAbsent; do
  expect_now "$a" inactive "healthy: $a is not firing"
done

echo "== phase 2: scale the exporter to zero ($(date +%T))"
kubectl -n "$NS" scale deploy/ragleap-postgres-exporter --replicas=0
expect RagleapAvailabilityFastBurn firing 600 "outage: RagleapAvailabilityFastBurn fires"
expect PostgresExporterDown firing 600 "outage: PostgresExporterDown fires"
expect_now RagleapTargetAbsent inactive "outage: RagleapTargetAbsent stays quiet (the up series exists, value 0)"
expect_webhook 'FIRING.*PostgresExporterDown|PostgresExporterDown.*FIRING' 240 "delivery: PostgresExporterDown reached the stand-in receiver"
curl -s "http://127.0.0.1:$AM_PORT/api/v2/alerts?active=true" | python3 -c "
import sys, json
names = [a['labels'].get('alertname') for a in json.load(sys.stdin)]
print('AlertManager active:', names)
sys.exit(0 if 'PostgresExporterDown' in names else 1)
" && record "PASS  AlertManager holds PostgresExporterDown as active" || { FAILS=$((FAILS + 1)); record "FAIL  AlertManager does not list PostgresExporterDown"; }

echo "== phase 3: scale the exporter back to one ($(date +%T))"
kubectl -n "$NS" scale deploy/ragleap-postgres-exporter --replicas=1
kubectl -n "$NS" rollout status deploy/ragleap-postgres-exporter --timeout=180s
expect PostgresExporterDown inactive 240 "recovery: PostgresExporterDown clears"
expect RagleapAvailabilityFastBurn inactive 600 "recovery: RagleapAvailabilityFastBurn clears"
expect_webhook 'RESOLVED.*PostgresExporterDown|PostgresExporterDown.*RESOLVED' 480 "delivery: the resolved notification reached the receiver (group_interval is 5m)"

echo "== phase 4: upgrade with the exporter disabled while slo.enabled still lists it ($(date +%T))"
helm upgrade "$REL" "$CH" -n "$NS" --reuse-values --set postgresExporter.enabled=false --wait --timeout 300s
kubectl -n "$NS" rollout status deploy/ragleap-prometheus --timeout=180s
kill "$PF_PROM" 2>/dev/null || true
pf ragleap-prometheus "$PROM_PORT" 9090 PF_PROM || stop "Prometheus port-forward failed after the upgrade"
expect RagleapTargetAbsent firing 900 "vanished target: RagleapTargetAbsent fires"
expect_webhook 'FIRING.*RagleapTargetAbsent|RagleapTargetAbsent.*FIRING' 240 "delivery: RagleapTargetAbsent reached the stand-in receiver"

echo
echo "== SUMMARY ($(date +%T))"
for r in "${RESULTS[@]}"; do echo "$r"; done
echo "Not exercised: RagleapAvailabilitySlowBurn firing, a real Slack or email send, Loki and Grafana, multi-node behaviour."
echo "Single kind node, stand-in Postgres and receiver, Prometheus with little history (burn-rate windows average only existing data)."
if [ "$FAILS" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "$FAILS CHECK(S) FAILED"; exit 1; fi
