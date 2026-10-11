import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const base = process.env.FUSION_BASE_URL || 'http://127.0.0.1:8765';
const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
async function api(route, body) {
  const response = await fetch(`${base}/api/${route}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  assert.ok(response.ok, `${route}: ${response.status} ${response.ok ? '' : await response.text()}`);
  return response.json();
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function applied(expected) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const s = await api('state');
    assert.ok(!s.renderer.error, s.renderer.error);
    if (s.renderer.applied_revision === s.revision && s.renderer.applied_field_key === s.field_ref.key &&
        Object.entries(expected).every(([key, value]) => s.state[key] === value)) return s;
    await delay(100);
  }
  throw new Error(`Snapshot did not apply: ${JSON.stringify(expected)}`);
}
async function complete(requestId) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const record = await api(`actions/${requestId}`);
    if (['completed', 'failed', 'cancelled'].includes(record.status)) {
      assert.equal(record.status, 'completed', JSON.stringify(record));
      return record;
    }
    await delay(100);
  }
  throw new Error(`Action did not finish: ${requestId}`);
}

async function sustainedSliderInput(page) {
  await api('state', { scenario: 'nominal', power: 1200, flow: 1, inlet: 300, phase: 0.65,
    mode: 'temperature', tab: 'explore', playing: false, orbit: false });
  await applied({ scenario: 'nominal', power: 1200, flow: 1, inlet: 300, phase: 0.65, mode: 'temperature' });
  await page.waitForFunction(() => Number(document.querySelector('#power-range').value) === 1200);
  try {
    await page.evaluate(async () => {
      const slider = document.querySelector('#power-range');
      const stream = window.FusionStreamer;
      const originalRequest = stream?.request;
      const originalFetch = window.fetch;
      const evidence = { sent: [], input: [], pending: 0, startedAt: performance.now(), releasedAt: null };
      window.__sliderInputEvidence = evidence;
      const observe = (transport, power, invoke) => {
        const record = { transport, power, sentAt: performance.now() };
        evidence.sent.push(record);
        evidence.pending += 1;
        return Promise.resolve().then(invoke).then(result => {
          record.accepted = transport === 'rtwt' ? result?.accepted === true : result.ok;
          return result;
        }).catch(error => {
          record.error = String(error);
          throw error;
        }).finally(() => { record.completedAt = performance.now(); evidence.pending -= 1; });
      };
      // Observe the production transport; every change still comes from its DOM input handler.
      if (originalRequest) stream.request = function (type, payload, ...args) {
        if (type !== 'fusion_set_state' || !Number.isFinite(payload?.state?.power)) {
          return originalRequest.call(this, type, payload, ...args);
        }
        return observe('rtwt', payload.state.power, () => originalRequest.call(this, type, payload, ...args));
      };
      window.fetch = function (input, init) {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.pathname === '/api/state' && init?.method === 'POST') {
          const patch = JSON.parse(init.body);
          if (Number.isFinite(patch.power)) return observe('http', patch.power, () => originalFetch.call(this, input, init));
        }
        return originalFetch.call(this, input, init);
      };
      window.__restoreSliderInputObserver = () => {
        window.fetch = originalFetch;
        if (originalRequest) stream.request = originalRequest;
        delete window.__restoreSliderInputObserver;
        delete window.__sliderInputEvidence;
      };
      slider.focus();
      for (let index = 0; index < 50; index++) {
        slider.value = String(1200 + Math.floor(index / 3) * 50);
        evidence.input.push({ power: Number(slider.value), at: performance.now() });
        slider.dispatchEvent(new Event('input', { bubbles: true }));
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      slider.value = '2200';
      slider.dispatchEvent(new Event('input', { bubbles: true }));
      evidence.releasedAt = performance.now();
      slider.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const final = await applied({ power: 2200, mode: 'temperature', playing: false });
    await page.waitForFunction(() => {
      const evidence = window.__sliderInputEvidence;
      return evidence.pending === 0 && evidence.sent.some(record => record.power === 2200 && record.accepted);
    }, {}, { timeout: 30000 });
    const evidence = await page.evaluate(() => window.__sliderInputEvidence);
    const intermediate = evidence.sent.filter(record => record.sentAt < evidence.releasedAt &&
      record.power > 1200 && record.power < 2200 && record.accepted);
    assert.equal(evidence.input.length, 50);
    assert.ok(evidence.releasedAt - evidence.startedAt >= 1000);
    assert.ok(new Set(intermediate.map(record => record.power)).size >= 2,
      `Continuous input must submit distinct intermediate values before release: ${JSON.stringify(evidence)}`);
    assert.ok(!evidence.sent.some(record => record.error || !record.accepted), JSON.stringify(evidence.sent));
    return { ...evidence, finalRevision: final.revision, appliedRevision: final.renderer.applied_revision,
      finalFieldKey: final.field_ref.key, appliedFieldKey: final.renderer.applied_field_key };
  } finally {
    await page.evaluate(() => window.__restoreSliderInputObserver?.());
  }
}

async function stateTransportFaults(page) {
  await page.locator('#power-range').evaluate(slider => slider.blur());
  await api('state', { power: 1200, selected: '', playing: false, orbit: false });
  await applied({ power: 1200 });
  await page.waitForFunction(() => Number(document.querySelector('#power-range').value) === 1200);
  await page.evaluate(() => {
    const stream = window.FusionStreamer, originalFetch = window.fetch;
    const connected = Object.getOwnPropertyDescriptor(stream, 'connected');
    // Exercise the production HTTP fallback without closing the video connection.
    Object.defineProperty(stream, 'connected', { configurable: true, get: () => false });
    const fault = window.__stateFault = { mode: 'slow', attempts: [], staleHeld: false, postHeld: false };
    window.fetch = async function (input, init) {
      const url = new URL(input instanceof Request ? input.url : input, location.href);
      if (url.pathname !== '/api/state') return originalFetch.call(this, input, init);
      if (init?.method !== 'POST') {
        if (fault.failHealthOnce) {
          fault.failHealthOnce = false;
          fault.healthFailed = true;
          throw new TypeError('Injected service outage');
        }
        if (fault.mode === 'slow' && !fault.staleHeld) {
          const response = await originalFetch.call(this, input, init);
          fault.staleHeld = true;
          return new Promise(resolve => { fault.releaseGet = () => resolve(response); });
        }
        return originalFetch.call(this, input, init);
      }
      const patch = JSON.parse(init.body);
      fault.attempts.push({ power: patch.power, time: performance.now() });
      if (fault.mode === 'slow') {
        fault.postHeld = true;
        await new Promise(resolve => { fault.releasePost = resolve; });
      }
      const transient = fault.mode === 'pause' || (fault.mode === 'retry' && fault.attempts.length <= 2);
      if (transient || fault.mode === 'reject') {
        return new Response(JSON.stringify({ error: 'Injected state failure' }), {
          status: transient ? 503 : 400, headers: { 'Content-Type': 'application/json' },
        });
      }
      return originalFetch.call(this, input, init);
    };
    window.__restoreStateFault = () => {
      fault.releaseGet?.(); fault.releasePost?.();
      window.fetch = originalFetch;
      Object.defineProperty(stream, 'connected', connected);
      delete window.__restoreStateFault;
    };
  });
  const emit = power => page.evaluate(value => {
    const slider = document.querySelector('#power-range');
    slider.value = String(value);
    slider.dispatchEvent(new Event('input', { bubbles: true }));
    slider.dispatchEvent(new Event('change', { bubbles: true }));
    slider.blur();
  }, power);
  const mode = value => page.evaluate(value => {
    window.__stateFault.mode = value;
    window.__stateFault.attempts = [];
  }, value);
  const evidence = {};
  try {
    await page.waitForFunction(() => window.__stateFault.staleHeld);
    await emit(1300);
    await page.waitForFunction(() => window.__stateFault.postHeld);
    await page.evaluate(() => window.__stateFault.releaseGet());
    await page.waitForTimeout(150);
    assert.equal(await page.locator('#power-range').inputValue(), '1300', 'Old GET must preserve the in-flight input');
    evidence.staleGetPreservedValue = 1300;
    await page.evaluate(() => window.__stateFault.releasePost());
    await applied({ power: 1300 });
    await page.waitForTimeout(200);

    await mode('retry');
    await emit(1350);
    await page.waitForFunction(() => window.__stateFault.attempts.length === 1);
    await emit(1450);
    await applied({ power: 1450 });
    evidence.transientAttempts = await page.evaluate(() => window.__stateFault.attempts);
    assert.deepEqual(evidence.transientAttempts.map(item => item.power), [1350, 1450, 1450], 'Retries must preserve the latest input');
    await page.waitForTimeout(200);

    await mode('pause');
    await emit(1550);
    await page.waitForFunction(() => window.__stateFault.attempts.length === 3);
    await page.waitForTimeout(1500);
    evidence.boundedAttempts = await page.evaluate(() => window.__stateFault.attempts.length);
    assert.equal(evidence.boundedAttempts, 3, 'Unavailable writes must stop after two retries');
    assert.equal(await page.locator('#power-range').inputValue(), '1550', 'Paused retries retain the unsaved intent');
    assert.ok(await page.locator('#connection').evaluate(element => element.classList.contains('error')));
    await page.evaluate(() => { window.__stateFault.failHealthOnce = true; });
    await page.waitForFunction(() => window.__stateFault.healthFailed);
    await page.evaluate(() => { window.__stateFault.mode = 'success'; });
    await applied({ power: 1550 });
    evidence.recoveredAttempts = await page.evaluate(() => window.__stateFault.attempts.length);
    assert.equal(evidence.recoveredAttempts, 4, 'A confirmed service recovery resumes the retained input');
    await page.waitForTimeout(200);

    await mode('reject');
    await emit(1650);
    await page.waitForFunction(() => window.__stateFault.attempts.length === 1);
    evidence.rejectionFeedback = await page.locator('#toast').innerText();
    await page.waitForTimeout(1500);
    evidence.rejectedAttempts = await page.evaluate(() => window.__stateFault.attempts.length);
    assert.equal(evidence.rejectedAttempts, 1, 'Validation rejection must not retry');
    assert.equal((await api('state')).state.power, 1550);
    assert.equal(await page.locator('#power-range').inputValue(), '1550');
    return evidence;
  } finally {
    await page.evaluate(() => window.__restoreStateFault?.());
  }
}

const original = await api('state');
const browser = await chromium.launch({ channel: 'msedge', headless: true,
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const errors = [];
page.on('pageerror', error => errors.push(String(error)));
const checks = [];
const check = (name, evidence) => { checks.push({ name, evidence }); console.log(name); };
try {
  await api('state', { playing: false, orbit: false, design: 'conventional', equilibrium: 'reference', mode: 'assembly' });
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 60000 });
  let s = await applied({ design: 'conventional', equilibrium: 'reference' });
  check('versioned_fields_applied', s.field_ref);
  check('continuous_slider_submits_before_release_and_applies_final', await sustainedSliderInput(page));
  check('state_transport_race_retry_recovery_and_rejection', await stateTransportFaults(page));

  const commands = Array.from({ length: 100 }, () => ({ type: 'measure_clear', request_id: randomUUID(), server_epoch: s.server_epoch, renderer_epoch: s.renderer.renderer_epoch }));
  const records = await Promise.all(commands.map(command => api('action', command)));
  assert.equal(new Set(records.map(record => record.seq)).size, 100);
  const completed = await Promise.all(records.map(record => complete(record.request_id)));
  const retry = await api('action', commands[0]);
  assert.equal(retry.seq, records[0].seq);
  assert.equal(retry.status, 'completed');
  check('burst_100_actions_and_retry', { completed: completed.length, duplicateSeq: retry.seq });

  const preserved = (await api('state')).field_ref;
  await api('state', { opacity: 0.9, cutaway: 40 });
  s = await applied({ opacity: 0.9, cutaway: 40 });
  assert.deepEqual(s.field_ref, preserved);
  check('view_changes_reuse_physics', s.field_ref.key);
  await api('state', { opacity: 1, cutaway: 80, mode: 'heatflux', power: 2000, phase: 1 });

  for (const design of ['conventional', 'longleg']) {
    await page.locator('#design-select').selectOption(design);
    for (const equilibrium of ['reference', 'rampup', 'sof', 'eof', 'rampdown']) {
      await page.locator('#equilibrium-select').selectOption(equilibrium);
      s = await applied({ design, equilibrium });
      assert.equal(s.result.design, design);
      assert.equal(s.result.equilibrium, equilibrium);
      assert.ok(s.field_ref.topology_key.startsWith(design));
      const b = s.result.power_budget;
      assert.ok(Math.abs(b.closure_residual_MW) < 0.001);
      assert.ok(Math.abs(b.absorbed_thermal_MW + b.unresolved_MW - b.requested_thermal_MW) < 0.001);
      assert.ok(b.full_machine_pfc_area_m2 < 3000);
      check(`design_equilibrium_${design}_${equilibrium}`, {
        fieldKey: s.field_ref.key, absorbedMW: b.absorbed_thermal_MW,
        unresolvedMW: b.unresolved_MW, strikes: s.result.strike_points,
      });
    }
    await page.locator('#equilibrium-select').selectOption('reference');
    await applied({ design, equilibrium: 'reference' });
    await delay(2000);
    await page.screenshot({ path: `${output}/reliability-${design}-heatflux.png` });
  }

  await page.locator('[data-tab="compare"]').click();
  await api('state', { scenario: 'highload' });
  await page.locator('[data-mode="delta_temperature"]').click();
  s = await applied({ mode: 'delta_temperature', scenario: 'highload' });
  assert.ok(s.result.comparison.delta.peak_temperature_C > 0);
  assert.ok(s.result.color_ranges.delta_temperature[0] < 0);
  assert.equal(s.result.color_ranges.delta_temperature[0], -s.result.color_ranges.delta_temperature[1]);
  await delay(2000);
  await page.screenshot({ path: `${output}/reliability-delta-temperature.png` });
  check('difference_field', s.result.color_ranges.delta_temperature);
  await page.locator('[data-lang="en"]').click();
  assert.equal(await page.locator('[data-i18n="powerBalance"]').innerText(), 'POWER BALANCE');
  await page.locator('[data-lang="zh"]').click();
  assert.equal(await page.locator('[data-i18n="powerBalance"]').innerText(), '功率收支');
  check('bilingual_new_controls', true);

  const exported = await api('export');
  assert.equal(exported.result.design, 'longleg');
  assert.ok(exported.provenance.source_record);
  assert.equal(exported.field_ref.key, exported.result.field_ref.key);
  check('export_matches_context', exported.field_ref);
  assert.deepEqual(errors, []);
  await writeFile(`${output}/reliability.json`, JSON.stringify({ passed: true, checks, errors }, null, 2));
  console.log(JSON.stringify({ passed: true, checks: checks.length }));
} catch (error) {
  await writeFile(`${output}/reliability.json`, JSON.stringify({ passed: false, checks, errors, failure: String(error), cause: String(error.cause || '') }, null, 2));
  throw error;
} finally {
  await browser.close();
  try {
    await api('state', original.state);
    if (!original.state.playing) {
      const restored = await applied(Object.fromEntries(Object.entries(original.state).filter(([key]) => key !== 'visible')));
      assert.deepEqual(restored.state.visible, original.state.visible);
    }
  }
  catch (error) { console.error('State restore failed:', String(error)); }
}
