import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
const original = (await snapshot()).state;
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server', ...(process.env.QA_SOFTWARE_BROWSER === '1' ? ['--disable-gpu'] : [])] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const frameStats = () => page.locator('video').evaluate(video => ({
  width: video.videoWidth, height: video.videoHeight,
  frames: video.getVideoPlaybackQuality().totalVideoFrames,
  dropped: video.getVideoPlaybackQuality().droppedVideoFrames, time: performance.now(),
}));
const intervalStats = (start, end) => {
  const seconds = (end.time - start.time) / 1000;
  const received = end.frames - start.frames;
  const dropped = end.dropped - start.dropped;
  return { videoFps: received / seconds, presentedFps: (received - dropped) / seconds, droppedFrames: dropped };
};
try {
  await post('state', { selected: '', orbit: false, playing: false });
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 45000 });
  await page.waitForTimeout(10000);
  const start = await frameStats();
  const renderer = (await snapshot()).renderer;
  assert.deepEqual([start.width, start.height], [2560, 1440]);
  assert.deepEqual(renderer.resolution, [start.width, start.height]);
  assert.equal(renderer.error, null);
  await page.waitForTimeout(4000);
  const end = await frameStats();
  await post('state', { orbit: true });
  await page.waitForTimeout(1500);
  const motionStart = await frameStats();
  await page.waitForTimeout(4000);
  const motionEnd = await frameStats();
  await post('state', { orbit: false });
  await post('action', { type: 'reset_camera' });
  await page.waitForTimeout(10000);
  await page.screenshot({ path: path.join(output, 'clarity-ui-1440p.png') });
  const encodedFrame = await page.locator('video').evaluate(video => {
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await writeFile(path.join(output, 'clarity-stream-1440p.png'), Buffer.from(encodedFrame, 'base64'));
  const capture = await post('action', { type: 'capture' });
  const captured = await complete(capture.request_id);
  const nativePNG = Buffer.from(await (await fetch(`${base}${captured.result.capture_url}`)).arrayBuffer());
  assert.equal(nativePNG.readUInt32BE(16), 2560);
  assert.equal(nativePNG.readUInt32BE(20), 1440);
  await writeFile(path.join(output, 'clarity-native-1440p.png'), nativePNG);
  assert.deepEqual(errors, []);
  const result = {
    browserCompositing: process.env.QA_SOFTWARE_BROWSER === '1' ? 'software' : 'default',
    resolution: renderer.resolution, spp: renderer.samples_per_pixel, totalSpp: renderer.accumulation_samples,
    static: intervalStats(start, end), motion: intervalStats(motionStart, motionEnd), errors,
  };
  await writeFile(path.join(output, 'clarity.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally {
  await post('state', original);
  await browser.close();
}
