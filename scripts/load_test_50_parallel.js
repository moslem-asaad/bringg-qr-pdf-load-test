// BRNGG-55375 -- 50 pre-planned runs started in parallel, stg2 merchant 60596.
//
// Scenario: 50 drivers, each with one pre-created, pre-accepted, pre-planned
// run (run row already exists, un-started) containing 3 tasks. This script
// fires ONE task-start per run, for all 50 runs at the same instant -- a
// deliberate simultaneous burst -- to observe templates-service/Gotenberg
// PDF-render pipeline + RabbitMQ behavior right at and beyond today's
// configured capacity (max_concurrent:4 + max_waiting:20 = 24).
//
// Everything else (creating the runs/tasks, accepting them) is SETUP and
// happens BEFORE this script runs, at whatever pace -- see
// scripts/how-to-start-a-run.md. This script's job is ONLY the parallel
// /start burst, which is the one thing that should be a deliberate, timed,
// confirmed event.
//
// Input file (RUNS_FILE): JSON array of {run_id, run_external_id, driver_id,
// primary_task_id, token} -- see scripts/test-data/k6b_runs_with_tokens.json
// (built by merging test-data/k6b_runs_parsed.json with driver login tokens).
//
// Run:
//   k6 run -e RUNS_FILE=test-data/k6b_runs_with_tokens.json load_test_50_parallel.js
//
// Outputs (always, via handleSummary):
//   test-data/k6_summary.json  -- raw k6 metrics data
//   test-data/k6_report.html   -- self-contained HTML report

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const BASE_URL = 'https://stg2-api.bringg.com';

const runs = new SharedArray('runs', function () {
	return JSON.parse(open(__ENV.RUNS_FILE));
});

const runStartedNewRun = new Counter('run_started_new_run');
const runStartedUnexpected = new Counter('run_started_unexpected_state');
const runStartFailed = new Counter('run_start_failed');
const runStartDuration = new Trend('run_start_duration', true);

export const options = {
	scenarios: {
		parallel_run_starts: {
			executor: 'shared-iterations',
			vus: runs.length,
			iterations: runs.length,
			maxDuration: '2m'
		}
	},
	thresholds: {
		// Informational only -- failures/shedding are the expected/measured
		// outcome here, not a script bug. This just guards against auth/URL
		// mistakes producing 100% transport-level failure.
		http_req_failed: ['rate<1.0']
	}
};

export default function () {
	const run = runs[__VU - 1]; // __VU is 1-indexed
	const url = `${BASE_URL}/api/tasks/${run.primary_task_id}/start`;

	const res = http.post(url, null, {
		headers: {
			'Content-Type': 'application/json',
			authorization: `Token token=${run.token}`,
			client: 'iOS'
		},
		tags: { name: 'task_start', run_external_id: run.run_external_id }
	});

	runStartDuration.add(res.timings.duration);

	let body;
	try {
		body = res.json();
	} catch (e) {
		body = null;
	}

	const success = body && body.success === true;
	const actualRunId = success ? body.task.run_id : null;
	const matchesExpectedRun = actualRunId === run.run_id;

	check(res, {
		'status is 200': (r) => r.status === 200,
		'success is true': () => success,
		'run_id matches the pre-planned run': () => matchesExpectedRun
	});

	if (success && matchesExpectedRun) {
		runStartedNewRun.add(1);
	} else if (success) {
		// Started, but attached to a DIFFERENT run than expected -- means the
		// pre-planned run wasn't actually "clean" (e.g. driver had another
		// open run). Worth knowing, not the same as a pipeline failure.
		runStartedUnexpected.add(1);
	} else {
		runStartFailed.add(1);
	}

	console.log(
		JSON.stringify({
			vu: __VU,
			driver_id: run.driver_id,
			expected_run_id: run.run_id,
			run_external_id: run.run_external_id,
			task_id: run.primary_task_id,
			status: res.status,
			success,
			actual_run_id: actualRunId,
			duration_ms: Math.round(res.timings.duration)
		})
	);
}

export function handleSummary(data) {
	const m = data.metrics;

	function ms(v) { return v != null ? (v / 1000).toFixed(2) + 's' : '—'; }
	function n(v)  { return v != null ? String(Math.round(v)) : '—'; }

	const dur    = m.run_start_duration  && m.run_start_duration.values;
	const httpDur = m.http_req_duration  && m.http_req_duration.values;
	const iters  = m.iterations          && m.iterations.values;
	const failed = m.http_req_failed     && m.http_req_failed.values;

	const started   = m.run_started_new_run       ? m.run_started_new_run.values.count       : '—';
	const unexpected= m.run_started_unexpected_state ? m.run_started_unexpected_state.values.count : 0;
	const startFail = m.run_start_failed           ? m.run_start_failed.values.count           : 0;
	const totalIter = iters ? iters.count : '—';
	const failRate  = failed ? (failed.rate * 100).toFixed(1) + '%' : '—';

	const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>k6 Load Test Report — 50-Parallel Runs</title>
<style>
  :root{--bg:#F5F7FB;--card:#fff;--border:#D6DBE8;--text:#1A2035;--muted:#5A6480;--faint:#8C96B0;--ok:#059669;--warn:#D97706;--mono:'Menlo','Consolas',monospace}
  *{box-sizing:border-box}
  body{margin:0 auto;max-width:820px;padding:32px 20px;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}
  h1{font-size:20px;margin:0 0 4px}
  .eyebrow{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#0090A8;margin-bottom:6px}
  .meta{font:12px/1 var(--mono);color:var(--muted);margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border)}
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
<div class="eyebrow">BRNGG-55375 · Spain DeCA QR Compliance · stg2</div>
<h1>k6 Load Test — 50-Parallel /start Burst</h1>
<div class="meta">merchant 60596 &nbsp;·&nbsp; runs 65277–65326 &nbsp;·&nbsp; ${new Date().toISOString().replace('T',' ').slice(0,19)} UTC</div>

<div class="tiles">
  <div class="tile"><div class="tile-lbl">Iterations</div><div class="tile-val ${startFail === 0 ? 'ok' : 'warn'}">${totalIter} / ${runs.length}</div></div>
  <div class="tile"><div class="tile-lbl">HTTP failures</div><div class="tile-val ${failed && failed.rate === 0 ? 'ok' : 'warn'}">${failRate}</div></div>
  <div class="tile"><div class="tile-lbl">Runs started (new)</div><div class="tile-val ok">${started}</div></div>
  <div class="tile"><div class="tile-lbl">Unexpected state</div><div class="tile-val ${unexpected === 0 ? 'ok' : 'warn'}">${unexpected}</div></div>
</div>

<div class="sec-lbl">/start request latency (run_start_duration)</div>
<div class="card">
<table>
  <thead><tr><th>Metric</th><th>min</th><th>med</th><th>avg</th><th>p(90)</th><th>p(95)</th><th>max</th></tr></thead>
  <tbody>
    <tr>
      <td>run_start_duration</td>
      <td>${ms(dur && dur.min)}</td>
      <td>${ms(dur && dur.med)}</td>
      <td>${ms(dur && dur.avg)}</td>
      <td>${ms(dur && dur['p(90)'])}</td>
      <td>${ms(dur && dur['p(95)'])}</td>
      <td>${ms(dur && dur.max)}</td>
    </tr>
    <tr>
      <td>http_req_duration</td>
      <td>${ms(httpDur && httpDur.min)}</td>
      <td>${ms(httpDur && httpDur.med)}</td>
      <td>${ms(httpDur && httpDur.avg)}</td>
      <td>${ms(httpDur && httpDur['p(90)'])}</td>
      <td>${ms(httpDur && httpDur['p(95)'])}</td>
      <td>${ms(httpDur && httpDur.max)}</td>
    </tr>
  </tbody>
</table>
</div>

<div class="sec-lbl">Custom counters</div>
<div class="card">
<table>
  <thead><tr><th>Counter</th><th>count</th></tr></thead>
  <tbody>
    <tr><td>run_started_new_run</td><td>${n(m.run_started_new_run && m.run_started_new_run.values.count)}</td></tr>
    <tr><td>run_started_unexpected_state</td><td>${n(m.run_started_unexpected_state && m.run_started_unexpected_state.values.count)}</td></tr>
    <tr><td>run_start_failed</td><td>${n(m.run_start_failed && m.run_start_failed.values.count)}</td></tr>
    <tr><td>http_reqs (total)</td><td>${n(m.http_reqs && m.http_reqs.values.count)}</td></tr>
  </tbody>
</table>
</div>

<div class="ftr">Generated by k6 handleSummary &nbsp;·&nbsp; raw data: <code>test-data/k6_summary.json</code></div>
</body>
</html>`;

	return {
		'test-data/k6_summary.json': JSON.stringify(data, null, 2),
		'test-data/k6_report.html': html,
	};
}
