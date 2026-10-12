import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
const codeHashes = {};
for (const name of ['kit/apps/fusion_twin.kit', 'kit/extensions/fusion.twin.bridge/fusion/twin/bridge/extension.py',
  'kit/extensions/fusion.twin.bridge/fusion/twin/bridge/nvidia_workflow.py', 'kit/workflow/workflow.toml', 'tools/qa/nvidia.mjs']) {
  codeHashes[name] = createHash('sha256').update(await readFile(new URL(`../../${name}`, import.meta.url))).digest('hex');
}
const original = (await snapshot()).state;
const browser = await chromium.launch({ channel: 'msedge', headless: process.env.QA_HEADLESS !== '0',
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(String(error)));
const check = (name, evidence) => { checks.push({ name, evidence }); console.log(name); };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function settled(expected, { volume = false, renderMode, quality,
  recoverControlError = false, minimumStandardWrites = 0 } = {}) {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    const s = await snapshot(), r = s.renderer;
    assert.ok(!r.error, r.error);
    assert.ok(!r.volume_error, r.volume_error);
    if (!recoverControlError) assert.ok(!r.control_error, r.control_error);
    if (r.ready && r.server_epoch === s.server_epoch && r.rtwt_ready &&
        !r.control_pending && !r.control_error &&
        r.rtwt_standard_writes >= minimumStandardWrites &&
        r.applied_revision === s.revision && r.applied_field_key === s.field_ref.key &&
        Object.entries(expected).every(([k, v]) => s.state[k] === v) &&
        (!renderMode || r.render_mode === renderMode) && (!quality || r.quality === quality) &&
        (!volume || (!r.volume_pending && r.applied_volume_field_key === s.field_ref.key &&
          r.volume_mask_angle === s.state.cutaway && r.volume_style === s.state.volumeStyle))) return s;
    await delay(100);
  }
  throw new Error(`NVIDIA workflow did not settle: ${JSON.stringify(expected)}`);
}
async function request(name, payload = {}) {
  return page.evaluate(({ name, payload }) => window.FusionStreamer.request(name, payload, 45000), { name, payload });
}
async function capture(name) {
  await delay(2500);
  await page.screenshot({ path: `${output}/${name}-ui.png` });
  const accepted = await post('action', { type: 'capture' });
  const record = await complete(accepted.request_id);
  const png = Buffer.from(await (await fetch(`${base}${record.result.capture_url}`)).arrayBuffer());
  assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], [2560, 1440]);
  await writeFile(`${output}/${name}-native.png`, png);
}
try {
  await post('state', { design: 'conventional', equilibrium: 'sof', scenario: 'nominal', phase: 1,
    power: 2000, heating: 50, neon: false, flow: 1, inlet: 300,
    mode: 'assembly', volumeStyle: 'plasma', heatScale: 'log', lineMotion: true, fieldLines: true,
    view: 'overview', cutaway: 80, explode: 0, opacity: 1, selected: '', orbit: false, playing: false });
  await settled({ mode: 'assembly' }, { renderMode: 'RealTimePathTracing', quality: 'detail' });
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4 && window.FusionStreamer.connected, {}, { timeout: 60000 });
  const manifest = await request('get_control_manifest');
  assert.equal(manifest.knobs.length, 20);
  assert.equal(new Set(manifest.knobs.map(knob => knob.key)).size, 20);
  for (const key of ['design', 'equilibrium', 'power', 'cutaway', 'mode', 'heating', 'neon', 'heatScale', 'volumeStyle', 'lineMotion']) {
    assert.ok(manifest.knobs.some(knob => knob.key === key), key);
  }
  assert.ok(manifest.knobs.find(knob => knob.key === 'mode').values.includes('volume'));
  assert.deepEqual(manifest.knobs.find(knob => knob.key === 'volumeStyle').values, ['plasma', 'temperature']);
  assert.deepEqual(manifest.knobs.find(knob => knob.key === 'heatScale').values, ['log', 'linear']);
  check('rtwt_manifest_over_webrtc', manifest);
  const before = await snapshot();
  await page.locator('[data-mode="volume"]').click();
  let s = await settled({ mode: 'volume' }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.ok(s.renderer.rtwt_remote_writes > before.renderer.rtwt_remote_writes);
  assert.deepEqual((await request('get_state')).mode, 'volume');
  assert.ok(s.renderer.index_fields.includes('colors'));
  assert.equal(s.renderer.index_source_field, 'Temperature');
  assert.equal(s.renderer.index_native_volume, true);
  assert.equal(s.renderer.volume_roundtrip, 'exact');
  assert.equal(s.renderer.index_composite, true);
  assert.equal(s.renderer.index_depth_mode, 3);
  assert.equal(s.renderer.render_mode, 'RealTimePathTracing');
  assert.match(s.renderer.engine, /RTX Real-Time 2\.0/);
  assert.equal(s.renderer.rt2_enabled, true);
  assert.equal(s.renderer.sampling_strategy, 'temporal_reconstruction');
  assert.equal(s.renderer.rtwt_control_count, 20);
  assert.deepEqual(s.renderer.volume_grid, [128, 128, 112]);
  assert.equal(s.renderer.volume_grid_voxels, 128 * 128 * 112);
  assert.equal(s.renderer.volume_units, 'keV');
  assert.equal(s.renderer.volume_style, 'plasma');
  assert.deepEqual(s.renderer.volume_colormap.domain, [0, 40]);
  await page.waitForFunction(() => document.querySelector('#field-legend').hidden &&
    document.querySelector('[data-volume-style="plasma"]').getAttribute('aria-pressed') === 'true');
  check('ui_rtwt_write_and_index_volume', s.renderer);
  await capture('nvidia-conventional-volume');

  const plasmaField = s.field_ref.key, plasmaVolume = s.renderer.applied_volume_key;
  const plasmaMap = s.renderer.volume_colormap.rgba;
  await page.locator('[data-volume-style="temperature"]').click();
  s = await settled({ volumeStyle: 'temperature' }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.equal(s.field_ref.key, plasmaField);
  assert.equal(s.renderer.applied_volume_key, plasmaVolume);
  assert.deepEqual(s.renderer.volume_colormap.domain, [0, 40]);
  assert.notDeepEqual(s.renderer.volume_colormap.rgba, plasmaMap);
  await page.waitForFunction(() => !document.querySelector('#field-legend').hidden &&
    document.querySelector('[data-volume-style="temperature"]').getAttribute('aria-pressed') === 'true' &&
    document.querySelector('#legend-unit').textContent === 'keV' &&
    Array.from(document.querySelectorAll('#legend-ticks span'), node => Number(node.textContent)).join(',') === '0,20,40');
  await capture('nvidia-conventional-temperature');
  check('volume_style_changes_transfer_only_with_fixed_temperature_legend', {
    field: s.field_ref.key, volume: s.renderer.applied_volume_key,
    domain: s.renderer.volume_colormap.domain, actualRange: s.renderer.volume_range_keV,
    grid: s.renderer.volume_grid, styles: ['plasma', s.renderer.volume_style],
  });
  await page.locator('[data-volume-style="plasma"]').click();
  s = await settled({ volumeStyle: 'plasma' }, { volume: true, renderMode: 'RealTimePathTracing' });

  // Exercise the stock RTWT set_state_request wire event, including its USD notice
  // -> validated solver -> immutable field -> native IndeX completion path.
  const standardBefore = s;
  const standardReply = await request('set_state', { state: { heating: 65, neon: true } });
  assert.equal(standardReply, true);
  s = await settled({ heating: 65, neon: true }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.ok(s.revision > standardBefore.revision);
  assert.ok(s.renderer.rtwt_standard_writes > standardBefore.renderer.rtwt_standard_writes);
  assert.notEqual(s.field_ref.key, standardBefore.field_ref.key);
  assert.notEqual(s.renderer.applied_volume_key, standardBefore.renderer.applied_volume_key);
  assert.equal(s.renderer.applied_volume_field_key, s.field_ref.key);
  assert.equal(s.result.power_budget.requested_thermal_MW - standardBefore.result.power_budget.requested_thermal_MW, 15);
  assert.equal(s.renderer.volume_roundtrip, 'exact');
  const stockState = await request('get_state');
  assert.equal(stockState.heating, 65);
  assert.equal(stockState.neon, true);
  check('standard_rtwt_set_state_commits_solver_and_native_volume', {
    request: 'set_state', response: standardReply, writes: s.renderer.rtwt_standard_writes,
    previousField: standardBefore.field_ref.key, field: s.field_ref.key,
    previousVolume: standardBefore.renderer.applied_volume_key, volume: s.renderer.applied_volume_key,
    inputPowerMW: s.result.power_budget.requested_thermal_MW, revision: s.revision,
    appliedRevision: s.renderer.applied_revision, resultRevision: s.renderer.rtwt_result_revision,
  });
  assert.equal(await request('set_state', { state: { heating: 50, neon: false } }), true);
  s = await settled({ heating: 50, neon: false }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.equal(s.field_ref.key, standardBefore.field_ref.key);
  assert.equal(s.renderer.applied_volume_key, standardBefore.renderer.applied_volume_key);

  // The stock handler acknowledges the USD write first; validation and rollback
  // complete asynchronously through the same solver path as a legal write.
  const rejectedBefore = s;
  const rejectedReply = await request('set_state', { state: { heating: 21 } });
  assert.equal(rejectedReply, true);
  let rejected;
  const rejectionDeadline = Date.now() + 60000;
  while (Date.now() < rejectionDeadline) {
    const current = await snapshot(), r = current.renderer;
    assert.ok(!r.error, r.error);
    assert.ok(!r.volume_error, r.volume_error);
    if (r.control_error && !r.control_pending) {
      rejected = current;
      break;
    }
    await delay(100);
  }
  assert.ok(rejected, 'Invalid standard write did not report its completed rollback');
  assert.match(rejected.renderer.control_error, /heating/i);
  assert.equal(rejected.revision, rejectedBefore.revision);
  assert.deepEqual(rejected.state, rejectedBefore.state);
  assert.equal(rejected.field_ref.key, rejectedBefore.field_ref.key);
  assert.equal(rejected.renderer.applied_field_key, rejectedBefore.field_ref.key);
  assert.equal(rejected.renderer.applied_volume_field_key, rejectedBefore.field_ref.key);
  assert.equal(rejected.renderer.rtwt_standard_writes, rejectedBefore.renderer.rtwt_standard_writes);
  assert.equal((await request('get_state')).heating, 50);
  check('standard_rtwt_invalid_value_preserves_solver_and_rolls_back_usd', {
    request: 'set_state', rejectedHeating: 21, response: rejectedReply,
    error: rejected.renderer.control_error, revision: rejected.revision,
    field: rejected.field_ref.key, usdHeating: 50,
  });

  assert.equal(await request('set_state', { state: { heating: 65 } }), true);
  s = await settled({ heating: 65, neon: false }, { volume: true, renderMode: 'RealTimePathTracing',
    recoverControlError: true, minimumStandardWrites: rejectedBefore.renderer.rtwt_standard_writes + 1 });
  assert.notEqual(s.field_ref.key, rejectedBefore.field_ref.key);
  assert.equal((await request('get_state')).heating, 65);
  check('standard_rtwt_legal_write_clears_error_and_applies_native_field', {
    error: s.renderer.control_error, revision: s.revision, field: s.field_ref.key,
    appliedVolumeField: s.renderer.applied_volume_field_key, usdHeating: 65,
  });
  assert.equal(await request('set_state', { state: { heating: 50 } }), true);
  s = await settled({ heating: 50, neon: false }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.equal(s.field_ref.key, standardBefore.field_ref.key);

  const rapidBefore = s;
  const rapidReplies = await page.evaluate(() => Promise.all([
    window.FusionStreamer.request('set_state', { state: { heating: 65 } }, 45000),
    window.FusionStreamer.request('set_state', { state: { heating: 50 } }, 45000),
  ]));
  assert.deepEqual(rapidReplies, [true, true]);
  s = await settled({ heating: 50, neon: false }, { volume: true, renderMode: 'RealTimePathTracing',
    minimumStandardWrites: rapidBefore.renderer.rtwt_standard_writes + 1 });
  assert.equal(s.field_ref.key, rapidBefore.field_ref.key);
  assert.equal(s.renderer.applied_volume_key, rapidBefore.renderer.applied_volume_key);
  assert.equal((await request('get_state')).heating, 50);
  check('standard_rtwt_rapid_return_to_committed_value_keeps_last_write', {
    heatingSequence: [50, 65, 50], responses: rapidReplies,
    writes: s.renderer.rtwt_standard_writes - rapidBefore.renderer.rtwt_standard_writes,
    field: s.field_ref.key, appliedVolumeField: s.renderer.applied_volume_field_key,
    revision: s.revision, appliedRevision: s.renderer.applied_revision, usdHeating: 50,
  });

  const firstKey = s.renderer.applied_volume_key, hits = s.renderer.volume_cache_hits;
  assert.equal((await request('fusion_set_state', { state: { cutaway: 60 } })).accepted, true);
  s = await settled({ cutaway: 60 }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.notEqual(s.renderer.applied_volume_key, firstKey);
  await request('fusion_set_state', { state: { cutaway: 80 } });
  s = await settled({ cutaway: 80 }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.equal(s.renderer.applied_volume_key, firstKey);
  assert.ok(s.renderer.volume_cache_hits > hits);
  check('cache_hit_and_cutaway_invalidation', { key: firstKey, hits: s.renderer.volume_cache_hits, misses: s.renderer.volume_cache_misses });

  const oldField = s.field_ref.key;
  await page.locator('[data-design="longleg"]').click();
  s = await settled({ design: 'longleg' }, { volume: true, renderMode: 'RealTimePathTracing' });
  assert.notEqual(s.field_ref.key, oldField);
  assert.equal((await request('get_state')).design, 'longleg');
  check('volume_design_switch', { field: s.field_ref, volume: s.renderer.applied_volume_key });
  await capture('nvidia-longleg-volume');
  const cache = await request('fusion_get_cache');
  assert.equal(cache.applied_volume_field_key, s.field_ref.key);
  await page.locator('[data-mode="assembly"]').click();
  s = await settled({ mode: 'assembly' }, { renderMode: 'RealTimePathTracing', quality: 'detail' });
  assert.equal(s.renderer.render_mode, 'RealTimePathTracing');
  assert.match(s.renderer.engine, /RTX Real-Time 2\.0/);
  assert.equal(s.renderer.rt2_enabled, true);
  assert.equal(s.renderer.samples_per_pixel, null);
  assert.equal(s.renderer.accumulation_samples, null);
  assert.equal(s.renderer.sampling_strategy, 'temporal_reconstruction');
  assert.equal((await request('get_state')).mode, 'assembly');
  check('assembly_restores_rt2_detail', { mode: s.renderer.render_mode, engine: s.renderer.engine,
    quality: s.renderer.quality, spp: s.renderer.samples_per_pixel, totalSpp: s.renderer.accumulation_samples });
  assert.equal((await request('fusion_set_state', { state: { orbit: true } })).accepted, true);
  s = await settled({ mode: 'assembly', orbit: true }, { renderMode: 'RealTimePathTracing', quality: 'interaction' });
  assert.match(s.renderer.engine, /RTX Real-Time 2\.0/);
  assert.equal(s.renderer.rt2_enabled, true);
  assert.equal(s.renderer.sampling_strategy, 'temporal_reconstruction');
  const movingEngine = { mode: s.renderer.render_mode, engine: s.renderer.engine, quality: s.renderer.quality };
  assert.equal((await request('fusion_set_state', { state: { orbit: false } })).accepted, true);
  await complete((await post('action', { type: 'reset_camera', view: 'overview' })).request_id);
  s = await settled({ mode: 'assembly', orbit: false }, { renderMode: 'RealTimePathTracing', quality: 'detail' });
  assert.match(s.renderer.engine, /RTX Real-Time 2\.0/);
  assert.equal(s.renderer.rt2_enabled, true);
  assert.equal(s.renderer.sampling_strategy, 'temporal_reconstruction');
  check('assembly_motion_and_settled_use_rt2', { moving: movingEngine,
    settled: { mode: s.renderer.render_mode, engine: s.renderer.engine, quality: s.renderer.quality } });
  const restoredVolumes = [];
  for (const [design, heating] of [['conventional', 20], ['longleg', 35], ['conventional', 50]]) {
    await post('state', { mode: 'assembly' });
    await settled({ mode: 'assembly' });
    const hiddenField = (await snapshot()).renderer.applied_volume_field_key;
    await post('state', { mode: 'volume', design, heating, neon: false });
    s = await settled({ mode: 'volume', design, heating }, { volume: true, renderMode: 'RealTimePathTracing' });
    assert.notEqual(s.field_ref.key, hiddenField);
    assert.equal(s.renderer.applied_volume_field_key, s.field_ref.key);
    assert.equal(s.renderer.volume_roundtrip, 'exact');
    restoredVolumes.push({ design, heating, field: s.field_ref.key, volume: s.renderer.applied_volume_key });
  }
  check('new_fields_execute_after_hidden_volume_is_shown', restoredVolumes);
  await post('state', original);
  await settled({ mode: original.mode, design: original.design }, { volume: original.mode === 'volume' });
  const diagnostics = await page.evaluate(() => window.FusionStreamer.diagnostics);
  assert.equal(diagnostics.timeouts, 0);
  assert.deepEqual(errors, []);
  check('data_channel_requests_complete', diagnostics);
  await writeFile(`${output}/nvidia.json`, JSON.stringify({ passed: true, codeHashes, checks, errors }, null, 2));
} catch (error) {
  await writeFile(`${output}/nvidia.json`, JSON.stringify({ passed: false, codeHashes, checks, errors, failure: String(error) }, null, 2));
  throw error;
} finally {
  try { await post('state', original); }
  finally { await browser.close(); }
}
