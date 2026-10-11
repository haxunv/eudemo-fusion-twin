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
  'kit/extensions/fusion.twin.bridge/fusion/twin/bridge/nvidia_workflow.py', 'tools/qa/nvidia.mjs']) {
  codeHashes[name] = createHash('sha256').update(await readFile(new URL(`../../${name}`, import.meta.url))).digest('hex');
}
const original = (await snapshot()).state;
const browser = await chromium.launch({ channel: 'msedge', headless: true,
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const errors = [], checks = [];
page.on('pageerror', error => errors.push(String(error)));
const check = (name, evidence) => { checks.push({ name, evidence }); console.log(name); };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function settled(expected, { volume = false, renderMode, quality } = {}) {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    const s = await snapshot(), r = s.renderer;
    assert.ok(!r.error, r.error);
    assert.ok(!r.volume_error, r.volume_error);
    if (r.ready && r.server_epoch === s.server_epoch && r.rtwt_ready &&
        r.applied_revision === s.revision && r.applied_field_key === s.field_ref.key &&
        Object.entries(expected).every(([k, v]) => s.state[k] === v) &&
        (!renderMode || r.render_mode === renderMode) && (!quality || r.quality === quality) &&
        (!volume || (!r.volume_pending && r.applied_volume_field_key === s.field_ref.key && r.volume_mask_angle === s.state.cutaway))) return s;
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
  await post('state', { design: 'conventional', equilibrium: 'reference', scenario: 'nominal', phase: 1,
    mode: 'assembly', view: 'overview', cutaway: 80, explode: 0, opacity: 1, selected: '', orbit: false, playing: false });
  await settled({ mode: 'assembly' }, { renderMode: 'RealTimePathTracing', quality: 'detail' });
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4 && window.FusionStreamer.connected, {}, { timeout: 60000 });
  const manifest = await request('get_control_manifest');
  for (const key of ['design', 'equilibrium', 'power', 'cutaway', 'mode']) assert.ok(manifest.knobs.some(knob => knob.key === key), key);
  assert.ok(manifest.knobs.find(knob => knob.key === 'mode').values.includes('volume'));
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
  check('ui_rtwt_write_and_index_volume', s.renderer);
  await capture('nvidia-conventional-volume');

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
  await page.locator('#design-select').selectOption('longleg');
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
