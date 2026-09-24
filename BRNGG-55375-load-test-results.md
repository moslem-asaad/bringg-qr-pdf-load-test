# BRNGG-55375 — 50-Parallel Load Test Results

---

## Batch 1

**Test window:** 2026-09-22 15:48:21Z – 15:48:27Z (burst in 2.5 seconds)
**Runs:** 65277–65326 · merchant 60596

### k6 — /start burst (50 runs, all fired simultaneously)

| Metric | Value |
|---|---|
| Requests | 50 / 50 ✓ (0 failures) |
| All checks passed | ✓ status=200, success=true, run_id matched |
| Median latency | 1.66s |
| p90 / p95 / max | 2.08s / 2.21s / 2.27s |

### Pipeline outcomes (all 50 resolved)

| Outcome | Count | % |
|---|---|---|
| webhook_delivered | 48 | 96% |
| render_returned_failure (shed) | 2 | 4% |

### End-to-end latency (run:started → webhook)

| Outcome | p50 | p95 | max |
|---|---|---|---|
| webhook_delivered | 8.0s | 13.6s | 13.8s |
| shed (fast-fail) | 770ms | 1.4s | 1.4s |

### Pipeline resource usage (Gotenberg dashboard)

| Metric | Value |
|---|---|
| Gotenberg CPU max | 0.197 cores |
| Gotenberg memory max | 1.20 GiB |
| Chromium queue peak | 8 requests waiting |
| Chromium restarts | 1 (within 1h window) |
| templates-service memory | 229 – 296 MiB |

### RabbitMQ

| Queue | Max depth | Max unacked | Consumers | Peak publish | Peak deliver |
|---|---|---|---|---|---|
| background tasks | 0 | 39 | 10 | 56.2 msg/s | 41.4 msg/s |
| templates-service | 0 | 37 | 2 | 5.8 msg/s | 0 msg/s |

---

## Batch 2

**Test window:** 2026-09-22 16:21:21Z – 16:21:24Z (burst in 3.4 seconds)
**Runs:** 65328–65377 · merchant 60596

### k6 — /start burst (50 runs, all fired simultaneously)

| Metric | Value |
|---|---|
| Requests | 50 / 50 ✓ (0 failures) |
| All checks passed | ✓ status=200, success=true, run_id matched |
| Median latency | 1.80s |
| p90 / p95 / max | 2.78s / 3.18s / 3.21s |

### Pipeline outcomes (all 50 resolved)

| Outcome | Count | % |
|---|---|---|
| webhook_delivered | 49 | 98% |
| render_returned_failure (shed) | 1 | 2% |

### End-to-end latency (run:started → webhook)

| Outcome | p50 | p95 | max |
|---|---|---|---|
| webhook_delivered | 9.2s | 14.6s | 15.9s |
| shed (fast-fail) | 524ms | — | 524ms |

### Pipeline resource usage (Gotenberg dashboard)

| Metric | Value |
|---|---|
| Gotenberg CPU max | 0.222 cores |
| Gotenberg memory max | 1.01 GiB |
| Chromium queue peak | 8 requests waiting |
| Chromium restarts | 1 (within 1h window) |
| templates-service memory | 230 – 313 MiB |

### RabbitMQ

| Queue | Max depth | Max unacked | Consumers | Peak publish | Peak deliver |
|---|---|---|---|---|---|
| background tasks | 0 | 30 | 10 | 1.0 msg/s | 4.4 msg/s |
| templates-service | 0 | 39 | 2 | 0 msg/s | 0 msg/s |

---

## Summary across both batches

| | Batch 1 | Batch 2 |
|---|---|---|
| webhook_delivered | 48 / 50 (96%) | 49 / 50 (98%) |
| shed failures | 2 (4%) | 1 (2%) |
| /start median latency | 1.66s | 1.80s |
| /start max latency | 2.27s | 3.21s |
| E2E p50 (webhook) | 8.0s | 9.2s |
| E2E max (webhook) | 13.8s | 15.9s |

## Failure analysis (Batches 1 & 2)

All 3 failures across Batches 1 & 2 were `shed` — `pdf_renderer.ts`'s own gate rejected work because `pendingCount ≥ max_waiting` (`max_concurrent:4` + `max_waiting:20` = 24-slot budget momentarily exceeded by the simultaneous burst). No Gotenberg-level failures; no queue backlog in either run.

96–98% success at 50-concurrent was the stable baseline of the original config.

---

## Batch 3 — pLimit gate removed

**Test window:** 2026-09-23 04:31:21Z – 04:31:25Z (burst in 3.4 seconds)
**Runs:** 65382–65431 · merchant 60596
**Config change:** `pLimit` concurrency gate removed from `pdf_renderer.ts` on `staging` — all 50 renders go straight to Gotenberg with no queue budget.

### k6 — /start burst (50 runs, all fired simultaneously)

| Metric | Value |
|---|---|
| Requests | 50 / 50 ✓ (0 failures) |
| All checks passed | ✓ status=200, success=true, run_id matched |
| Median latency | 1.85s |
| p90 / p95 / max | 2.91s / 3.10s / 3.23s |

### Pipeline outcomes (all 50 resolved)

| Outcome | Count | % |
|---|---|---|
| webhook_delivered | 50 | 100% |
| shed / render failures | 0 | 0% |

### End-to-end latency (run:started → webhook)

| Outcome | p50 | p95 | max |
|---|---|---|---|
| webhook_delivered | 8.5s | 14.2s | 14.8s |

### Pipeline resource usage (Gotenberg dashboard)

| Metric | Value |
|---|---|
| Gotenberg CPU max | 0.197 cores |
| Gotenberg memory max | 1.20 GiB |
| Chromium queue peak | 31 requests waiting |
| Chromium restarts | 0 |
| templates-service memory | 354 – 427 MiB |

### RabbitMQ

| Queue | Max depth | Max unacked | Consumers |
|---|---|---|---|
| background tasks | 0 | 36 | 10 |
| templates-service | 0 | 31 | 2 |

---

## Summary across all three batches

| | Batch 1 (gate: 4+20) | Batch 2 (gate: 4+20) | Batch 3 (no gate) |
|---|---|---|---|
| webhook_delivered | 48 / 50 (96%) | 49 / 50 (98%) | 50 / 50 (100%) |
| shed failures | 2 (4%) | 1 (2%) | 0 (0%) |
| /start median latency | 1.66s | 1.80s | 1.85s |
| /start max latency | 2.27s | 3.21s | 3.23s |
| E2E p50 (webhook) | 8.0s | 9.2s | 8.5s |
| E2E max (webhook) | 13.8s | 15.9s | 14.8s |
| Gotenberg CPU max | 0.197 cores | 0.222 cores | 0.197 cores |
| Gotenberg queue peak | 8 waiting | 8 waiting | 31 waiting |

### Key finding

Removing the pLimit gate eliminated all shed failures — 50/50 delivered. Gotenberg CPU stayed flat (~0.2 cores) across all three batches — it was never the bottleneck. What changed is the **Chromium internal queue depth**: with the gate on, only 8 requests ever queued inside Gotenberg; with the gate off, all 50 arrived simultaneously and 31 queued at peak. Gotenberg absorbed them without restarts or CPU spikes. Memory stayed in the same band (~1 GiB). The shed failures in Batches 1 & 2 were caused entirely by our pLimit gate, not by Gotenberg capacity.
