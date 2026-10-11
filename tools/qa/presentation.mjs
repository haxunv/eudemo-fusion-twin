import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';

const base = 'http://127.0.0.1:8765';
const output = path.resolve('../../runtime/qa');
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
const checks = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
async function settled(predicate, label) {
  for (let i = 0; i < 100; i++) {
    const s = await (await fetch(`${base}/api/state`)).json();
    if (predicate(s) && s.renderer.applied_revision >= s.revision && !s.renderer.error) { checks.push(label); return s; }
    await page.waitForTimeout(100);
  }
  throw new Error(label);
}
async function capture(name) {
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(output, name) });
  return page.locator('video').evaluate(video => {
    const canvas = document.createElement('canvas');
    canvas.width = 160; canvas.height = 120;
    const context = canvas.getContext('2d');
    // Keep the same central reactor region across native stream resolutions.
    const roi = { x: 7 / 32, y: 1 / 6, width: 7 / 16, height: 3 / 4 };
    context.drawImage(video, video.videoWidth * roi.x, video.videoHeight * roi.y, video.videoWidth * roi.width, video.videoHeight * roi.height, 0, 0, 160, 120);
    return Array.from(context.getImageData(0, 0, 160, 120).data);
  });
}
try {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 30000 });
  await page.locator('#reset-view-button').click();
  await settled(s => s.state.selected === '' && !s.renderer.selected, 'Reset clears USD selection');
  await page.locator('#assembly-button').click();
  await page.locator('[data-component="blanket"]').click();
  await settled(s => s.renderer.selected === 'blanket', 'Native selection established');
  await page.locator('[data-close="assembly-drawer"]').click();
  await page.locator('[data-mode="temperature"]').click();
  await settled(s => s.state.mode === 'temperature' && !s.state.visible.plasma && !s.renderer.selected, 'Temperature reveals fields and clears selection');
  await page.locator('#scenario-select').selectOption('highload');
  await settled(s => s.state.scenario === 'highload', 'High load fields applied');
  const temperatureFrame = await capture('10-temperature-clean.png');
  await page.locator('[data-mode="magnetic"]').click();
  await settled(s => s.state.mode === 'magnetic' && !s.state.visible.plasma, 'Magnetic lines visible without opaque plasma');
  const magneticFrame = await capture('11-magnetic-clean.png');
  const pixelDifference = temperatureFrame.reduce((sum, value, index) => sum + Math.abs(value - magneticFrame[index]), 0) / temperatureFrame.length;
  assert.ok(pixelDifference > 1, `Scientific modes must change decoded RTX pixels: ${pixelDifference}`);
  checks.push('Temperature and magnetic modes change actual decoded RTX image');
  await page.locator('#reset-view-button').click();
  await settled(s => s.state.mode === 'magnetic' && !s.state.visible.plasma, 'Reset preserves scientific mode visibility');
  await page.locator('[data-mode="assembly"]').click();
  await page.locator('#scenario-select').selectOption('nominal');
  await settled(s => s.state.mode === 'assembly' && s.state.visible.plasma && s.state.scenario === 'nominal', 'Assembly restores plasma default');
  await page.locator('[data-lang="zh"]').click();
  await capture('12-final-zh.png');
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, 'presentation.json'), JSON.stringify({ passed: true, checks, pixelDifference, errors }, null, 2));
  console.log(JSON.stringify({ passed: true, checks: checks.length, pixelDifference, errors }));
} catch (error) {
  await writeFile(path.join(output, 'presentation.json'), JSON.stringify({ passed: false, checks, errors, failure: error.stack }, null, 2));
  throw error;
} finally { await browser.close(); }
