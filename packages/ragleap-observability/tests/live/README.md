# Manual live test of the SLO alerts

`slo-live-test.sh` runs the SLO rules from `origin/main` on a real Prometheus (one container, no Kubernetes)
with a stand-in target. It takes roughly 20-25 minutes and needs Docker, the pinned Prometheus image already
pulled, about 3 GB of free disk and 600 MB of free memory. It is **not** run in CI.

    nohup bash packages/ragleap-observability/tests/live/slo-live-test.sh > ~/slo-live-test.log 2>&1 &

It checks that a healthy target fires nothing, that a stopped target fires `RagleapAvailabilityFastBurn` and
`PostgresExporterDown`, that a target removed from the scrape config fires `RagleapTargetAbsent`, and that each
alert clears again. It does not exercise slow-burn firing, AlertManager delivery or the Kubernetes wiring.
It removes the containers and network it creates.
