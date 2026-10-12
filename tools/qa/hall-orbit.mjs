import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
const label = process.env.QA_LABEL || '';
if (label) assert.match(label, /^[a-zA-Z0-9_-]+$/);
const prefix = `hall-orbit${label ? `-${label}` : ''}`;
const captureUI = process.env.QA_CAPTURE_UI !== '0';
await mkdir(output, { recursive: true });
const original = (await snapshot()).state;
const report = { passed: false, base, headless: false, captureUI,
  durationSeconds: 66, orbitRadiansPerSecond: 0.1,
  method: 'requestVideoFrameCallback presentation callbacks',
  thresholds: { presentedFps: 24, droppedRate: 0.05 },
  codeHashes: {}, samples: [], captures: [], errors: [] };
for (const name of ['tools/build_scene.py', 'kit/apps/fusion_twin.kit',
  'kit/extensions/fusion.twin.bridge/fusion/twin/bridge/extension.py', 'tools/qa/hall-orbit.mjs']) {
  report.codeHashes[name] = createHash('sha256')
    .update(await readFile(new URL(`../../${name}`, import.meta.url))).digest('hex');
}
const browser = await chromium.launch({ channel: 'msedge', headless: false,
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('pageerror', error => report.errors.push(String(error)));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function assertEngine(renderer) {
  assert.equal(renderer.render_mode, 'RealTimePathTracing');
  assert.match(renderer.engine, /RTX Real-Time 2\.0/);
  assert.equal(renderer.rt2_enabled, true);
  assert.equal(renderer.sampling_strategy, 'temporal_reconstruction');
}
function ready(s) {
  const r = s.renderer;
  assert.ok(!r.error, r.error);
  assert.ok(!r.volume_error, r.volume_error);
  assert.ok(!r.control_error, r.control_error);
  return r.ready && r.server_epoch === s.server_epoch && r.rtwt_ready && !r.control_pending &&
    r.applied_revision === s.revision && r.applied_field_key === s.field_ref.key &&
    (s.state.mode !== 'volume' || (!r.volume_pending && r.applied_volume_field_key === s.field_ref.key &&
      r.volume_mask_angle === s.state.cutaway && r.volume_style === s.state.volumeStyle));
}
async function waitRenderer(expected = {}, quality, walls) {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    const s = await snapshot();
    if (ready(s) && Object.entries(expected).every(([key, value]) => s.state[key] === value) &&
        (!quality || s.renderer.quality === quality) &&
        (!walls || JSON.stringify(s.renderer.hall_hidden_walls) === JSON.stringify(walls))) {
      assertEngine(s.renderer);
      return s;
    }
    await delay(100);
  }
  throw new Error(`Hall renderer did not settle: ${JSON.stringify(expected)}`);
}
async function videoSample() {
  return page.locator('video').evaluate(video => {
    const quality = video.getVideoPlaybackQuality();
    return { time: performance.now(), presented: window.__hallPresented,
      frames: quality.totalVideoFrames, dropped: quality.droppedVideoFrames,
      resolution: [video.videoWidth, video.videoHeight] };
  });
}
function difference(start, end) {
  const seconds = (end.time - start.time) / 1000;
  const presentedFrames = end.presented - start.presented;
  const totalVideoFrames = end.frames - start.frames;
  const dropped = end.dropped - start.dropped;
  return { seconds, presentedFrames, totalVideoFrames, dropped,
    presentedFps: presentedFrames / seconds, droppedRate: dropped / Math.max(1, totalVideoFrames) };
}
function aggregate(intervals) {
  const result = { seconds: 0, presentedFrames: 0, totalVideoFrames: 0, dropped: 0 };
  for (const interval of intervals) for (const key of Object.keys(result)) result[key] += interval[key];
  return { ...result, presentedFps: result.presentedFrames / result.seconds,
    droppedRate: result.dropped / Math.max(1, result.totalVideoFrames) };
}
function assertUnchanged(s, initial) {
  assert.ok(ready(s), 'The active field must remain fully applied during the orbit');
  assertEngine(s.renderer);
  assert.equal(s.field_ref.key, initial.field_ref.key);
  assert.equal(s.renderer.applied_volume_field_key, initial.field_ref.key);
  assert.equal(s.renderer.applied_volume_key, initial.renderer.applied_volume_key);
  assert.deepEqual(s.state.visible, initial.state.visible);
  assert.deepEqual(s.renderer.visible, initial.renderer.visible);
  assert.equal(s.state.mode, 'volume');
  assert.equal(s.state.fieldLines, true);
  assert.equal(s.state.lineMotion, true);
  assert.equal(s.renderer.line_motion, true);
  assert.ok(s.renderer.line_marker_vertices > 0);
  assert.equal(s.renderer.camera_path, '/World/Cameras/overview');
}

let failure;
try {
  const manifestResponse = await fetch(`${base}/api/manifest`);
  assert.ok(manifestResponse.ok);
  const manifest = await manifestResponse.json();
  await post('state', { design: 'conventional', equilibrium: 'sof', scenario: 'nominal', phase: 1,
    power: 2000, heating: 50, neon: false, flow: 1, inlet: 300,
    mode: 'volume', volumeStyle: 'plasma', heatScale: 'log', fieldLines: true, lineMotion: true,
    view: 'overview', tab: 'explore', cutaway: 80, explode: 0, opacity: 1, selected: '',
    orbit: false, playing: false,
    visible: Object.fromEntries(manifest.components.map(c => [c.id, c.default_visible !== false])) });
  await waitRenderer({ mode: 'volume', orbit: false }, 'detail');
  await complete((await post('action', { type: 'reset_camera', view: 'overview' })).request_id);
  const initial = await waitRenderer({ mode: 'volume', orbit: false }, 'detail', []);
  report.initial = { field: initial.field_ref.key, volume: initial.renderer.applied_volume_key,
    stateVisible: initial.state.visible, renderedVisible: initial.renderer.visible,
    hiddenWalls: initial.renderer.hall_hidden_walls, engine: initial.renderer.engine };
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video')?.readyState === 4 &&
    window.FusionStreamer?.connected, {}, { timeout: 60000 });
  await page.locator('video').evaluate(video => {
    window.__hallPresented = 0;
    const frame = () => { window.__hallPresented++; video.requestVideoFrameCallback(frame); };
    video.requestVideoFrameCallback(frame);
  });
  await delay(2000);
  await post('state', { orbit: true });
  const moving = await waitRenderer({ mode: 'volume', orbit: true }, 'interaction');
  assertUnchanged(moving, initial);
  const seenWalls = new Set(moving.renderer.hall_hidden_walls);
  let returnedToNone = false;
  const start = await videoSample();
  let previous = start, cleanStart = start;
  const cleanIntervals = [];
  const startTime = performance.now();
  console.log('hall-orbit: visible Edge ready; measuring 66 seconds');
  for (let second = 1; second <= 66; second++) {
    await delay(Math.max(0, startTime + second * 1000 - performance.now()));
    const [video, s] = await Promise.all([videoSample(), snapshot()]);
    assertUnchanged(s, initial);
    assert.equal(s.state.orbit, true);
    const hiddenWalls = s.renderer.hall_hidden_walls;
    assert.ok(Array.isArray(hiddenWalls));
    for (const wall of hiddenWalls) seenWalls.add(wall);
    if (seenWalls.size && hiddenWalls.length === 0) returnedToNone = true;
    const interval = difference(previous, video);
    report.samples.push({ second, elapsedSeconds: (video.time - start.time) / 1000,
      video, interval, hiddenWalls, engine: s.renderer.engine, renderMode: s.renderer.render_mode,
      quality: s.renderer.quality, renderResolution: s.renderer.render_resolution,
      revision: s.revision, field: s.field_ref.key });
    previous = video;
    if (second % 10 === 0) {
      console.log(`hall-orbit ${second}/66s: ${interval.presentedFps.toFixed(2)} presented FPS, ` +
        `${(interval.droppedRate * 100).toFixed(2)}% dropped, hidden=${hiddenWalls.join(',') || 'none'}`);
      const before = await videoSample();
      cleanIntervals.push(difference(cleanStart, before));
      const name = `${prefix}-${String(second).padStart(2, '0')}s.png`;
      if (captureUI) await page.screenshot({ path: `${output}/${name}` });
      const after = await videoSample();
      report.captures.push({ second, captured: captureUI, path: captureUI ? name : null,
        hiddenWalls, interval: difference(before, after) });
      cleanStart = after;
    }
  }
  const end = await videoSample();
  cleanIntervals.push(difference(cleanStart, end));
  report.fullOrbit = difference(start, end);
  report.outsideScreenshotCalls = aggregate(cleanIntervals);
  report.screenshotCalls = aggregate(report.captures.map(c => c.interval));
  report.seenWalls = [...seenWalls].sort();
  report.returnedToNoneDuringOrbit = returnedToNone;
  await post('state', { orbit: false });
  await waitRenderer({ mode: 'volume', orbit: false }, 'detail');
  await complete((await post('action', { type: 'reset_camera', view: 'overview' })).request_id);
  const reset = await waitRenderer({ mode: 'volume', orbit: false }, 'detail', []);
  assertUnchanged(reset, initial);
  report.resetHiddenWalls = reset.renderer.hall_hidden_walls;
  assert.deepEqual(report.seenWalls, ['BackWall', 'SideWall_0', 'SideWall_2']);
  assert.ok(returnedToNone, 'Near walls must become visible again during the orbit');
  assert.equal(report.captures.filter(c => c.captured).length, captureUI ? 6 : 0);
  assert.ok(report.fullOrbit.seconds >= 66, `Orbit lasted ${report.fullOrbit.seconds}s`);
  assert.ok(report.fullOrbit.presentedFps >= 24, `Orbit presentation below 24 FPS: ${report.fullOrbit.presentedFps}`);
  assert.ok(report.fullOrbit.droppedRate <= 0.05, `Orbit dropped more than 5%: ${report.fullOrbit.droppedRate}`);
  assert.deepEqual(report.errors, []);
  report.passed = true;
  console.log(`hall-orbit complete: ${report.fullOrbit.presentedFps.toFixed(2)} presented FPS, ` +
    `${(report.fullOrbit.droppedRate * 100).toFixed(2)}% dropped; all three walls hidden and restored`);
} catch (error) {
  failure = error;
  report.failure = String(error);
} finally {
  try {
    await post('state', { ...original, orbit: false, playing: false });
    await waitRenderer({ orbit: false, playing: false });
    await complete((await post('action', { type: 'reset_camera', view: original.view })).request_id);
    await post('state', original);
    await waitRenderer();
    report.restored = true;
  } catch (error) {
    report.restored = false;
    report.cleanupFailure = String(error);
    report.passed = false;
    failure ||= error;
  } finally {
    await browser.close();
    await writeFile(`${output}/${prefix}.json`, JSON.stringify(report, null, 2));
  }
}
if (failure) throw failure;
