import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
const original = (await snapshot()).state;
const mode = process.env.QA_MODE || 'assembly';
const stationaryMode = 'RealTimePathTracing';
const codeHashes = {};
for (const name of ['kit/apps/fusion_twin.kit', 'kit/extensions/fusion.twin.bridge/fusion/twin/bridge/extension.py',
  'kit/extensions/fusion.twin.bridge/fusion/twin/bridge/nvidia_workflow.py', 'tools/qa/performance.mjs']) {
  codeHashes[name] = createHash('sha256').update(await readFile(new URL(`../../${name}`, import.meta.url))).digest('hex');
}
const headless = process.env.QA_HEADLESS !== '0';
const browser = await chromium.launch({ channel: 'msedge', headless, args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.addInitScript(() => {
  const OriginalPeer = window.RTCPeerConnection;
  window.__qaPeers = [];
  window.RTCPeerConnection = class extends OriginalPeer {
    constructor(...args) { super(...args); window.__qaPeers.push(this); }
  };
});
async function waitRenderer(quality, renderMode, orbit) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    const s = await snapshot(), r = s.renderer;
    assert.ok(!r.error, r.error);
    assert.ok(!r.volume_error, r.volume_error);
    if (r.ready && r.server_epoch === s.server_epoch && r.applied_revision === s.revision &&
        r.applied_field_key === s.field_ref.key && s.state.mode === mode && s.state.orbit === orbit &&
        r.quality === quality && r.render_mode === renderMode &&
        (mode !== 'volume' || (!r.volume_pending && r.applied_volume_field_key === s.field_ref.key &&
          r.volume_mask_angle === s.state.cutaway))) return r;
    await page.waitForTimeout(100);
  }
  throw new Error(`Renderer did not reach ${quality}/${renderMode}: ${JSON.stringify((await snapshot()).renderer)}`);
}
function engineEvidence(renderer) {
  return { engine: renderer.engine, renderMode: renderer.render_mode, quality: renderer.quality,
    rt2Enabled: renderer.rt2_enabled, samplingStrategy: renderer.sampling_strategy,
    spp: renderer.samples_per_pixel, totalSpp: renderer.accumulation_samples,
    renderResolution: renderer.render_resolution, appliedFieldKey: renderer.applied_field_key };
}
function assertEngine(renderer, renderMode) {
  assert.equal(renderer.render_mode, renderMode);
  assert.match(renderer.engine, /RTX Real-Time 2\.0/);
  assert.equal(renderer.sampling_strategy, 'temporal_reconstruction');
  assert.equal(renderer.rt2_enabled, true);
  assert.equal(renderer.samples_per_pixel, null);
  assert.equal(renderer.accumulation_samples, null);
}
async function sample() {
  return page.evaluate(async () => {
    const video = document.querySelector('video');
    const quality = video.getVideoPlaybackQuality();
    const inbound = [];
    for (const peer of window.__qaPeers) {
      for (const report of (await peer.getStats()).values()) {
        if (report.type === 'inbound-rtp' && report.kind === 'video') inbound.push(report);
      }
    }
    return { time: performance.now(), resolution: [video.videoWidth, video.videoHeight],
      total: quality.totalVideoFrames, dropped: quality.droppedVideoFrames,
      presented: window.__qaPresented, inbound };
  });
}
function difference(start, end) {
  const seconds = (end.time - start.time) / 1000;
  const first = start.inbound[0], last = end.inbound[0];
  return { seconds, presentedFps: (end.presented - start.presented) / seconds,
    dropped: end.dropped - start.dropped,
    droppedRate: (end.dropped - start.dropped) / Math.max(1, end.total - start.total),
    receivedFps: first && last ? (last.framesReceived - first.framesReceived) / seconds : null,
    decodedFps: first && last ? (last.framesDecoded - first.framesDecoded) / seconds : null,
    decoder: last?.decoderImplementation, powerEfficientDecoder: last?.powerEfficientDecoder,
    decodeMsPerFrame: first && last ? (last.totalDecodeTime - first.totalDecodeTime) * 1000 / Math.max(1, last.framesDecoded - first.framesDecoded) : null,
  };
}
try {
  await post('state', { design: 'conventional', equilibrium: 'reference', scenario: 'nominal',
    phase: 1, mode, view: 'overview', cutaway: 80, explode: 0, opacity: 1,
    selected: '', orbit: false, playing: false });
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 45000 });
  await page.evaluate(() => {
    window.__qaPresented = 0;
    const video = document.querySelector('video');
    const frame = () => { window.__qaPresented++; video.requestVideoFrameCallback(frame); };
    video.requestVideoFrameCallback(frame);
  });
  const initialRenderer = await waitRenderer('detail', stationaryMode, false);
  await page.waitForTimeout(12000);
  const start = await sample();
  await page.waitForTimeout(4000);
  const still = await sample();
  await post('state', { orbit: true });
  await waitRenderer('interaction', 'RealTimePathTracing', true);
  await page.waitForTimeout(2000);
  const moving = await sample();
  await page.waitForTimeout(6000);
  const moved = await sample();
  const renderer = await waitRenderer('interaction', 'RealTimePathTracing', true);
  await post('state', { orbit: false });
  await complete((await post('action', { type: 'reset_camera' })).request_id);
  await waitRenderer('detail', stationaryMode, false);
  await page.waitForTimeout(12000);
  const settledRenderer = await waitRenderer('detail', stationaryMode, false);
  await page.mouse.move(800, 450);
  await page.mouse.down();
  const dragStart = await sample();
  for (let step = 1; step <= 60; step++) {
    await page.mouse.move(800 + step * 4, 450 + Math.sin(step / 10) * 40);
    await page.waitForTimeout(50);
  }
  const dragEnd = await sample();
  const dragRenderer = (await snapshot()).renderer;
  await page.mouse.up();
  await complete((await post('action', { type: 'reset_camera' })).request_id);
  await waitRenderer('detail', stationaryMode, false);
  await page.waitForTimeout(12000);
  const capture = await post('action', { type: 'capture' });
  const captured = await complete(capture.request_id);
  const restoredRenderer = await waitRenderer('detail', stationaryMode, false);
  const png = Buffer.from(await (await fetch(`${base}${captured.result.capture_url}`)).arrayBuffer());
  const captureResolution = [png.readUInt32BE(16), png.readUInt32BE(20)];
  const result = { mode, headless, codeHashes, browser: await browser.version(), resolution: moved.resolution, spp: renderer.samples_per_pixel,
    totalSpp: renderer.accumulation_samples, engine: renderer.render_mode,
    rendererEngine: renderer.engine,
    engines: { initial: engineEvidence(initialRenderer), orbit: engineEvidence(renderer),
      settledAfterOrbit: engineEvidence(settledRenderer), drag: engineEvidence(dragRenderer),
      settledAfterDrag: engineEvidence(restoredRenderer) },
    motionRenderResolution: renderer.render_resolution ?? renderer.resolution,
    settledRenderResolution: settledRenderer.render_resolution ?? settledRenderer.resolution,
    dragRenderResolution: dragRenderer.render_resolution, dragQuality: dragRenderer.quality,
    drag: difference(dragStart, dragEnd), captureResolution,
    static: difference(start, still), motion: difference(moving, moved), raw: { start, still, moving, moved } };
  const label = process.env.QA_LABEL || 'current';
  await writeFile(`${output}/performance-${label}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ ...result, raw: undefined }));
  assertEngine(initialRenderer, stationaryMode);
  assertEngine(renderer, 'RealTimePathTracing');
  assertEngine(settledRenderer, stationaryMode);
  assertEngine(dragRenderer, 'RealTimePathTracing');
  assertEngine(restoredRenderer, stationaryMode);
  assert.deepEqual(moved.resolution, renderer.resolution);
  assert.deepEqual(settledRenderer.render_resolution, settledRenderer.resolution);
  assert.deepEqual(captureResolution, settledRenderer.resolution);
  assert.equal(dragRenderer.quality, 'interaction');
  assert.deepEqual(dragRenderer.render_resolution, renderer.render_resolution);
  assert.ok(result.motion.presentedFps >= 24, `Motion presentation below 24 FPS: ${result.motion.presentedFps}`);
  assert.ok(result.drag.presentedFps >= 24, `Drag presentation below 24 FPS: ${result.drag.presentedFps}`);
  assert.ok(result.motion.droppedRate <= .05 && result.drag.droppedRate <= .05,
    `Motion/drag dropped more than 5% of video frames: ${result.motion.droppedRate}, ${result.drag.droppedRate}`);
} finally {
  try {
    await post('state', original);
    await complete((await post('action', { type: 'reset_camera' })).request_id);
  } finally { await browser.close(); }
}
