import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
import { base, snapshot, post } from './api.mjs';

const original = (await snapshot()).state;
const headless = process.env.QA_HEADLESS !== '0';
const browser = await chromium.launch({ channel: 'msedge', headless,
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
try {
  await post('state', { mode: 'temperature', view: 'section', orbit: false, playing: false });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto(base);
  await page.waitForFunction(() => document.querySelector('video').readyState === 4);
  await page.waitForTimeout(6000);
  const result = await page.evaluate(async () => {
    const video = document.querySelector('video');
    const frame = () => new Promise(resolve => video.requestVideoFrameCallback(resolve));
    const samples = {};
    for (const method of ['none', 'cpu-canvas', 'gpu-canvas', 'video-frame']) {
      const canvas = document.createElement('canvas');
      canvas.width = 192; canvas.height = 144;
      const context = canvas.getContext('2d', { willReadFrequently: method === 'cpu-canvas' });
      samples[method] = [];
      for (let i = 0; i < 4; i++) {
        const now = await frame(), start = performance.now();
        if (method.endsWith('canvas')) {
          context.drawImage(video, video.videoWidth * .18, video.videoHeight * .12,
            video.videoWidth * .5, video.videoHeight * .76, 0, 0, 192, 144);
          context.getImageData(0, 0, 192, 144);
        } else if (method === 'video-frame') {
          const source = new VideoFrame(video);
          const options = { format: 'RGBA' };
          await source.copyTo(new Uint8Array(source.allocationSize(options)), options);
          source.close();
        }
        samples[method].push({ readMs: performance.now() - start, frameTime: now });
      }
    }
    return samples;
  });
  const report = { headless, browser: await browser.version(), result,
    renderer: (await snapshot()).renderer };
  await writeFile(new URL(`../../runtime/qa/readback-${headless ? 'headless' : 'headed'}.json`, import.meta.url), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally { await post('state', original); await browser.close(); }
