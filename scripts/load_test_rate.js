// BRNGG-55375 — Rate-based PDF render load tests (templates-service + Gotenberg, no pLimit gate).
//
// Four scenarios, selected via SCENARIO env var:
//   baseline      1 req/s × 2 min   — baseline render latency with no competing load
//   find_capacity ramp 10→30/s × 10 min — find where p95 jumps or errors start
//   soak          30/s × 25 min     — sustained throughput
//   spike         30/s warm → 150/s × 1 min → 30/s recovery × 2 min
//
// Driver requirements (start + close + 0.5s sleep ≈ 2.5s cycle → each driver sustains ~0.4 req/s):
//   baseline:      5 drivers,  ~120 tasks total
//   find_capacity: 80 drivers, ~12 000 tasks total
//   soak:          80 drivers, ~45 000 tasks total
//   spike:        380 drivers, ~13 000 tasks total (380 needed at peak 150/s)
//
// Input (TASKS_FILE): JSON array from accept_rate_tasks.py — tasks sorted round-robin by
//   driver, so iterationInTest % tasks.length never assigns two concurrent iterations
//   to the same driver.
//
// Required env vars:
//   TASKS_FILE   path to accepted-tasks JSON  (e.g. test-data/rate_k6e_tasks.json)
//   ADMIN_TOKEN  company/admin token for bulk_close after each /start
//   SCENARIO     one of: baseline | find_capacity | soak | spike
//
// Output (handleSummary):
//   test-data/rate_<scenario>_<suffix>_summary.json
//   test-data/rate_<scenario>_<suffix>_report.html
//
// Recommended run command (live dashboard + HTML export):
//   K6_WEB_DASHBOARD=true \
//   K6_WEB_DASHBOARD_EXPORT=test-data/rate_soak_live.html \
//   k6 run \
//     -e TASKS_FILE=test-data/rate_k6e_tasks.json \
//     -e ADMIN_TOKEN=<admin_token> \
//     -e SCENARIO=soak \
//     load_test_rate.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend, Rate } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import exec from 'k6/execution';

const BASE_URL = 'https://stg2-api.bringg.com';

const SCENARIO = __ENV.SCENARIO || 'baseline';
const SUFFIX = __ENV.SCENARIO_SUFFIX || new Date().toISOString().slice(0, 16).replace(/[T:]/g, '-');

const tasks = new SharedArray('tasks', function () {
	return JSON.parse(open(__ENV.TASKS_FILE));
});

// --- custom metrics ---
const runStarted     = new Counter('run_started');
const runStartFailed = new Counter('run_start_failed');
const runCloseOk     = new Counter('run_close_ok');
const runCloseFailed = new Counter('run_close_failed');
const startDuration  = new Trend('start_duration', true);
const closeDuration  = new Trend('close_duration', true);
const errorRate      = new Rate('error_rate');

// --- scenario definitions ---
const SCENARIOS = {
	baseline: {
		executor: 'constant-arrival-rate',
		rate: 1,
		timeUnit: '1s',
		duration: '2m',
		preAllocatedVUs: 5,
		maxVUs: 10,
	},
	find_capacity: {
		executor: 'ramping-arrival-rate',
		startRate: 10,
		timeUnit: '1s',
		stages: [{ target: 30, duration: '10m' }],
		preAllocatedVUs: 90,
		maxVUs: 130,
	},
	soak: {
		executor: 'constant-arrival-rate',
		rate: 30,
		timeUnit: '1s',
		duration: '25m',
		preAllocatedVUs: 90,
		maxVUs: 130,
	},
	spike: {
		executor: 'ramping-arrival-rate',
		startRate: 30,
		timeUnit: '1s',
		stages: [
			{ target: 150, duration: '1m' },
			{ target: 30, duration: '2m' },
		],
		preAllocatedVUs: 400,
		maxVUs: 450,
	},
};

if (!SCENARIOS[SCENARIO]) {
	throw new Error(`Unknown SCENARIO="${SCENARIO}". Valid values: ${Object.keys(SCENARIOS).join(', ')}`);
}

export const options = {
	scenarios: { [SCENARIO]: SCENARIOS[SCENARIO] },
	thresholds: {
		// p95 render latency must stay under 10 s (Gotenberg has a 30s hard timeout;
		// 10 s gives headroom and flags saturation well before requests time out).
		start_duration: ['p(95)<10000'],
		// Hard cap: more than 5% of starts failing means the pipeline is shedding.
		error_rate: ['rate<0.05'],
	},
};

function closeRunWithRetry(runId, adminToken, maxAttempts = 5) {
	for (let attempt = 0; attempt < maxAttempts; attempt++) {
		const closeRes = http.post(
			`${BASE_URL}/runs/bulk_close`,
			JSON.stringify({ run_ids: [runId] }),
			{
				headers: {
					'Content-Type': 'application/json',
					authorization: `Token token=${adminToken}`,
				},
				tags: { name: 'run_close' },
			}
		);

		closeDuration.add(closeRes.timings.duration);

		let ok = false;
		if (closeRes.status === 200) {
			try {
				const body = closeRes.json();
				ok = !!(body && body.success === true);
			} catch {
				ok = false;
			}
		}

		if (ok) {
			runCloseOk.add(1);
			return true;
		}

		const retryable = closeRes.status === 0 || closeRes.status === 429 || closeRes.status >= 500;
		console.warn(`close failed run=${runId} http=${closeRes.status} attempt=${attempt + 1}/${maxAttempts}`);
		if (retryable && attempt < maxAttempts - 1) {
			sleep(Math.pow(2, attempt) * 0.25);
			continue;
		}
		break;
	}
	runCloseFailed.add(1);
	return false;
}

// --- VU function ---
export default function () {
	// Round-robin task assignment: iterationInTest is a monotonically increasing unique
	// counter per scenario iteration, so tasks[i % n] always refers to a different
	// driver when the tasks array is sorted round-robin by driver (see accept_rate_tasks.py).
	const idx = exec.scenario.iterationInTest % tasks.length;
	if (exec.scenario.iterationInTest >= tasks.length) {
		// We have more iterations than pre-seeded tasks. This should not happen in a
		// correctly sized run — the seed count must cover the full scenario duration.
		// Bail out of this iteration gracefully rather than re-starting an already-used task.
		console.warn(`iteration ${exec.scenario.iterationInTest} exceeds task pool size (${tasks.length}) — skipping`);
		runStartFailed.add(1);
		errorRate.add(1);
		return;
	}
	const task = tasks[idx];
	const adminToken = __ENV.ADMIN_TOKEN;

	// 1. Start the task — triggers the PDF render pipeline (templates-service → Gotenberg).
	const startRes = http.post(
		`${BASE_URL}/api/tasks/${task.primary_task_id}/start`,
		null,
		{
			headers: {
				'Content-Type': 'application/json',
				authorization: `Token token=${task.token}`,
				client: 'iOS',
			},
			tags: { name: 'task_start' },
		}
	);

	startDuration.add(startRes.timings.duration);

	let body;
	try { body = startRes.json(); } catch { body = null; }

	const started = body && body.success === true;
	const runId   = started && body.task ? body.task.run_id : null;

	check(startRes, {
		'start: status 200': (r) => r.status === 200,
		'start: success true': () => started,
	});

	if (started) {
		runStarted.add(1);
		errorRate.add(0);
	} else {
		runStartFailed.add(1);
		errorRate.add(1);
		console.warn(`start failed task=${task.primary_task_id} driver=${task.driver_id} http=${startRes.status} body=${startRes.body ? String(startRes.body).slice(0, 180) : ''}`);
	}

	// 2. Close the run so this driver can be reused for their next pre-accepted task.
	//    Without this, the driver stays in an open run and their next /start attaches
	//    to that run rather than starting a fresh one.
	//    Retry 429/5xx/network — a single close miss bricks that driver for the rest of the test.
	if (runId && adminToken) {
		closeRunWithRetry(runId, adminToken);
	}

	// Brief pause so the driver's run-close propagates before this VU could be
	// assigned another task for the same driver in the next iteration.
	sleep(0.5);
}

// --- HTML summary report ---
export function handleSummary(data) {
	const m = data.metrics;

	function ms(v)  { return v != null ? (v / 1000).toFixed(2) + 's' : '—'; }
	function n(v)   { return v != null ? String(Math.round(v)) : '—'; }
	function pct(v) { return v != null ? (v * 100).toFixed(1) + '%' : '—'; }

	const dur     = m.start_duration  && m.start_duration.values;
	const cDur    = m.close_duration  && m.close_duration.values;
	const httpDur = m.http_req_duration && m.http_req_duration.values;
	const iters   = m.iterations       && m.iterations.values;
	const failed  = m.http_req_failed  && m.http_req_failed.values;
	const errR    = m.error_rate       && m.error_rate.values;

	const totalIter  = iters  ? iters.count : '—';
	const failRate   = failed ? pct(failed.rate) : '—';
	const startedN   = n(m.run_started       && m.run_started.values.count);
	const startFailN = n(m.run_start_failed  && m.run_start_failed.values.count);
	const startFail  = m.run_start_failed ? m.run_start_failed.values.count : 0;
	const errRateStr = errR ? pct(errR.rate) : '—';

	const scenarioLabel = {
		baseline:      '1 req/s × 2 min',
		find_capacity: 'ramp 10→30/s × 10 min',
		soak:          '30/s × 25 min',
		spike:         '30/s → 150/s × 1 min → 30/s recovery × 2 min',
	}[SCENARIO] || SCENARIO;

	const testEndMs   = Date.now();
	const testStartMs = testEndMs - Math.round(data.state.testRunDurationMs || 0);
	const grafanaBase = 'https://grafana-pme.teleport.pme.gcloud.bringg.com/d/gotenberg-overview/gotenberg';
	const grafanaUrl  = `${grafanaBase}?var-environment=stg2&from=${testStartMs}&to=${testEndMs}`;

	const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>k6 Rate Load Test — ${SCENARIO}</title>
<style>
  :root{--bg:#F5F7FB;--card:#fff;--border:#D6DBE8;--text:#1A2035;--muted:#5A6480;--faint:#8C96B0;--ok:#059669;--warn:#D97706;--mono:'Menlo','Consolas',monospace}
  *{box-sizing:border-box}
  body{margin:0 auto;max-width:900px;padding:32px 20px;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}
  h1{font-size:20px;margin:0 0 4px}
  .eyebrow{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#0090A8;margin-bottom:6px}
  .meta{font:12px/1.6 var(--mono);color:var(--muted);margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border)}
  .tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:28px}
  @media(max-width:560px){.tiles{grid-template-columns:repeat(2,1fr)}}
  .tile{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px 16px}
  .tile-lbl{font-size:11px;font-weight:500;color:var(--muted);margin-bottom:5px}
  .tile-val{font:600 22px/1 var(--mono);color:var(--text);font-variant-numeric:tabular-nums}
  .tile-val.ok{color:var(--ok)}.tile-val.warn{color:var(--warn)}
  .sec-lbl{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);margin-bottom:10px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:20px}
  table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
  th{text-align:left;font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--faint);padding-bottom:8px;border-bottom:1px solid var(--border)}
  th:not(:first-child){text-align:right}
  td{padding:8px 0 0;color:var(--text)}
  td:first-child{color:var(--muted);font-size:12px}
  td:not(:first-child){text-align:right;font-family:var(--mono)}
  .ftr{border-top:1px solid var(--border);padding-top:14px;font-size:11px;color:var(--faint);margin-top:24px}
  code{font-family:var(--mono);font-size:11px;background:#EDF0F7;padding:1px 4px;border-radius:3px}
</style>
</head>
<body>
<div class="eyebrow">BRNGG-55375 · Spain DeCA QR Compliance · stg2 · no pLimit gate</div>
<h1>k6 Rate Load Test — ${SCENARIO}</h1>
<div class="meta">merchant 60596 &nbsp;·&nbsp; ${scenarioLabel} &nbsp;·&nbsp; ${new Date().toISOString().replace('T',' ').slice(0,19)} UTC</div>

<div class="tiles">
  <div class="tile"><div class="tile-lbl">Iterations</div><div class="tile-val">${totalIter}</div></div>
  <div class="tile"><div class="tile-lbl">HTTP failures</div><div class="tile-val ${failed && failed.rate === 0 ? 'ok' : 'warn'}">${failRate}</div></div>
  <div class="tile"><div class="tile-lbl">Runs started</div><div class="tile-val ok">${startedN}</div></div>
  <div class="tile"><div class="tile-lbl">Start failures</div><div class="tile-val ${startFail === 0 ? 'ok' : 'warn'}">${startFailN}</div></div>
</div>

<div class="sec-lbl">/start request latency</div>
<div class="card">
<table>
  <thead><tr><th>Metric</th><th>min</th><th>med</th><th>avg</th><th>p(90)</th><th>p(95)</th><th>p(99)</th><th>max</th></tr></thead>
  <tbody>
    <tr>
      <td>start_duration</td>
      <td>${ms(dur && dur.min)}</td>
      <td>${ms(dur && dur.med)}</td>
      <td>${ms(dur && dur.avg)}</td>
      <td>${ms(dur && dur['p(90)'])}</td>
      <td>${ms(dur && dur['p(95)'])}</td>
      <td>${ms(dur && dur['p(99)'])}</td>
      <td>${ms(dur && dur.max)}</td>
    </tr>
    <tr>
      <td>http_req_duration (all)</td>
      <td>${ms(httpDur && httpDur.min)}</td>
      <td>${ms(httpDur && httpDur.med)}</td>
      <td>${ms(httpDur && httpDur.avg)}</td>
      <td>${ms(httpDur && httpDur['p(90)'])}</td>
      <td>${ms(httpDur && httpDur['p(95)'])}</td>
      <td>${ms(httpDur && httpDur['p(99)'])}</td>
      <td>${ms(httpDur && httpDur.max)}</td>
    </tr>
    <tr>
      <td>close_duration (bulk_close)</td>
      <td>${ms(cDur && cDur.min)}</td>
      <td>${ms(cDur && cDur.med)}</td>
      <td>${ms(cDur && cDur.avg)}</td>
      <td>${ms(cDur && cDur['p(90)'])}</td>
      <td>${ms(cDur && cDur['p(95)'])}</td>
      <td>${ms(cDur && cDur['p(99)'])}</td>
      <td>${ms(cDur && cDur.max)}</td>
    </tr>
  </tbody>
</table>
</div>

<div class="sec-lbl">counters</div>
<div class="card">
<table>
  <thead><tr><th>Counter</th><th>count</th></tr></thead>
  <tbody>
    <tr><td>run_started</td><td>${n(m.run_started && m.run_started.values.count)}</td></tr>
    <tr><td>run_start_failed</td><td>${n(m.run_start_failed && m.run_start_failed.values.count)}</td></tr>
    <tr><td>run_close_ok</td><td>${n(m.run_close_ok && m.run_close_ok.values.count)}</td></tr>
    <tr><td>run_close_failed</td><td>${n(m.run_close_failed && m.run_close_failed.values.count)}</td></tr>
    <tr><td>error_rate</td><td>${errRateStr}</td></tr>
    <tr><td>http_reqs (total)</td><td>${n(m.http_reqs && m.http_reqs.values.count)}</td></tr>
  </tbody>
</table>
</div>

<div class="sec-lbl">Gotenberg (stg2) — fill from dashboard after run</div>
<div class="card">
  <div style="margin-bottom:12px;font-size:12px">
    <a href="${grafanaUrl}" target="_blank" style="color:#0090A8;word-break:break-all">${grafanaUrl}</a>
    <span style="font-size:11px;color:var(--muted);margin-left:6px">(time window pre-set to this test run)</span>
  </div>
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>
      <tr><td>CPU max (cores)</td><td>—</td></tr>
      <tr><td>Memory max (MB)</td><td>—</td></tr>
      <tr><td>Chromium queue peak</td><td>—</td></tr>
      <tr><td>Chromium restarts</td><td>—</td></tr>
    </tbody>
  </table>
</div>

<div class="sec-lbl">raw data</div>
<div class="card" style="font-size:13px;line-height:1.6">
  <strong>Raw k6 metrics:</strong> <code>test-data/rate_${SCENARIO}_${SUFFIX}_summary.json</code>
</div>

<div class="ftr">Generated by k6 handleSummary</div>
</body>
</html>`;

	const isoStart = new Date(testStartMs).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
	const isoEnd   = new Date(testEndMs).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
	const durationMin = Math.round((testEndMs - testStartMs) / 60000);

	const md = `## BRNGG-55375 — Rate Load Test: ${SCENARIO}

**Test window:** ${isoStart} – ${isoEnd} (${durationMin} min)
**Merchant:** 60596 (stg2)  ·  **Ticket:** BRNGG-55375
**Config:** pLimit gate removed from \`pdf_renderer.ts\` on staging

### k6 — /start (${scenarioLabel})

| Metric | Value |
|---|---|
| Requests | ${startedN} started / ${totalIter} iterations (${startFailN} start failures) |
| HTTP failures | ${failRate} |
| Median latency | ${ms(dur && dur.med)} |
| p90 / p95 / p99 / max | ${ms(dur && dur['p(90)'])} / ${ms(dur && dur['p(95)'])} / ${ms(dur && dur['p(99)'])} / ${ms(dur && dur.max)} |
| close latency (p50 / p95 / max) | ${ms(cDur && cDur.med)} / ${ms(cDur && cDur['p(95)'])} / ${ms(cDur && cDur.max)} |

### Pipeline outcomes

| Outcome | Count | % |
|---|---|---|
| webhook\\_delivered | — | — |
| render\\_failed / shed | — | — |

> Fill from Redash / backend after run. See runbook §5e.

### End-to-end latency (run:started → webhook)

| Outcome | p50 | p95 | max |
|---|---|---|---|
| webhook\\_delivered | — | — | — |
| failures | — | — | — |

> Fill from Redash after run.

### Gotenberg resource usage

| Metric | Value |
|---|---|
| CPU max (cores) | — |
| Memory max (MB) | — |
| Chromium queue peak | — |
| Chromium restarts | — |

> Dashboard: ${grafanaUrl}

### RabbitMQ

| Queue | Max depth | Max unacked | Consumers | Peak publish | Peak deliver |
|---|---|---|---|---|---|
| background tasks | — | — | — | — | — |
| templates-service | — | — | — | — | — |

> Fill from RabbitMQ management dashboard after run.

---
*Raw k6 data: \`test-data/rate_${SCENARIO}_${SUFFIX}_summary.json\`*
`;

	const meta = {
		scenario:    SCENARIO,
		suffix:      SUFFIX,
		testStartMs: testStartMs,
		testEndMs:   testEndMs,
	};

	return {
		[`test-data/rate_${SCENARIO}_${SUFFIX}_summary.json`]: JSON.stringify(data, null, 2),
		[`test-data/rate_${SCENARIO}_${SUFFIX}_meta.json`]:    JSON.stringify(meta, null, 2),
		[`test-data/rate_${SCENARIO}_${SUFFIX}_report.html`]:  html,
		[`test-data/rate_${SCENARIO}_${SUFFIX}_report.md`]:    md,
	};
}
