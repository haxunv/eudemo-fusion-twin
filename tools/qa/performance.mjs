import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const base = 'http://127.0.0.1:8765';
const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
const snapshot = async () => (await fetch(`${base}/api/state`)).json();
const post = async (route, value) => (await fetch(`${base}/api/${route}`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
})).json();
const original = (await snapshot()).state;
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.addInitScript(() => {
  const OriginalPeer = window.RTCPeerConnection;
  window.__qaPeers = [];
  window.RTCPeerConnection = class extends OriginalPeer {
    constructor(...args) { super(...args); window.__qaPeers.push(this); }
  };
});
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
    receivedFps: first && last ? (last.framesReceived - first.framesReceived) / seconds : null,
    decodedFps: first && last ? (last.framesDecoded - first.framesDecoded) / seconds : null,
    decoder: last?.decoderImplementation, powerEfficientDecoder: last?.powerEfficientDecoder,
    decodeMsPerFrame: first && last ? (last.totalDecodeTime - first.totalDecodeTime) * 1000 / Math.max(1, last.framesDecoded - first.framesDecoded) : null,
  };
}
try {
  await post('state', { orbit: false, playing: false });
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 45000 });
  await page.evaluate(() => {
    window.__qaPresented = 0;
    const video = document.querySelector('video');
    const frame = () => { window.__qaPresented++; video.requestVideoFrameCallback(frame); };
    video.requestVideoFrameCallback(frame);
  });
  await page.waitForTimeout(12000);
  const start = await sample();
  await page.waitForTimeout(4000);
  const still = await sample();
  await post('state', { orbit: true });
  await page.waitForTimeout(2000);
  const moving = await sample();
  await page.waitForTimeout(6000);
  const moved = await sample();
  const renderer = (await snapshot()).renderer;
  await post('state', { orbit: false });
  await post('action', { type: 'reset_camera' });
  await page.waitForTimeout(12000);
  const settledRenderer = (await snapshot()).renderer;
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
  await post('action', { type: 'reset_camera' });
  await page.waitForTimeout(12000);
  const capture = await post('action', { type: 'capture' });
  await page.waitForFunction(async seq => {
    const { renderer } = await (await fetch('/api/state')).json();
    return renderer.command_seq >= seq && !renderer.capture_pending;
  }, capture.command_seq, { timeout: 15000 });
  const png = Buffer.from(await (await fetch(`${base}/api/preview.png`)).arrayBuffer());
  const captureResolution = [png.readUInt32BE(16), png.readUInt32BE(20)];
  const result = { resolution: moved.resolution, spp: renderer.samples_per_pixel,
    totalSpp: renderer.accumulation_samples, engine: renderer.render_mode,
    motionRenderResolution: renderer.render_resolution ?? renderer.resolution,
    settledRenderResolution: settledRenderer.render_resolution ?? settledRenderer.resolution,
    dragRenderResolution: dragRenderer.render_resolution, dragQuality: dragRenderer.quality,
    drag: difference(dragStart, dragEnd), captureResolution,
    static: difference(start, still), motion: difference(moving, moved), raw: { start, still, moving, moved } };
  const label = process.env.QA_LABEL || 'current';
  await writeFile(`${output}/performance-${label}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ ...result, raw: undefined }));
  assert.deepEqual(moved.resolution, renderer.resolution);
  assert.deepEqual(settledRenderer.render_resolution, settledRenderer.resolution);
  assert.deepEqual(captureResolution, settledRenderer.resolution);
  assert.equal(dragRenderer.quality, 'interaction');
  assert.deepEqual(dragRenderer.render_resolution, renderer.render_resolution);
  assert.ok(result.motion.presentedFps >= 24, `Motion presentation below 24 FPS: ${result.motion.presentedFps}`);
  assert.ok(result.drag.presentedFps >= 24, `Drag presentation below 24 FPS: ${result.drag.presentedFps}`);
} finally {
  await post('state', original);
  await post('action', { type: 'reset_camera' });
  await browser.close();
}
