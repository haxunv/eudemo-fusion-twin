import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';

const base = 'http://127.0.0.1:8765';
const output = path.resolve('../../runtime/qa');
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1, acceptDownloads: true });
async function until(predicate) {
  for (let i = 0; i < 100; i++) {
    const s = await (await fetch(`${base}/api/state`)).json();
    if (predicate(s) && s.renderer.applied_revision >= s.revision && !s.renderer.error) return s;
    await page.waitForTimeout(100);
  }
  throw new Error('Renderer state did not settle');
}
async function surfaceClick(x, y) {
  const box = await page.locator('video').boundingBox();
  const aspect = await page.locator('video').evaluate(video => video.videoWidth / video.videoHeight);
  const width = Math.min(box.width, box.height * aspect);
  const height = width / aspect;
  await page.mouse.click(box.x + (box.width - width) / 2 + x * width, box.y + (box.height - height) / 2 + y * height);
}
try {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 30000 });
  await page.locator('[data-mode="assembly"]').click();
  await page.locator('#reset-view-button').click();
  await until(s => s.state.mode === 'assembly' && s.state.selected === '' && !s.renderer.selected);
  await page.locator('#measure-button').click();
  const beforeMeasurement = await (await fetch(`${base}/api/state`)).json();
  await page.locator('#start-measure-button').click();
  await page.locator('#measure-dialog').waitFor({ state: 'hidden' });
  await until(s => s.renderer.command_seq > beforeMeasurement.renderer.command_seq && !s.renderer.measurement);
  await surfaceClick(0.405, 0.42);
  await until(s => s.renderer.measurement?.type === 'point');
  await surfaceClick(0.43, 0.50);
  const measured = await until(s => s.renderer.measurement?.type === 'distance');
  assert.ok(measured.renderer.measurement.distance_m > 1);
  await page.locator('#measure-dialog').waitFor({ state: 'visible' });
  assert.ok((await page.locator('.measure-result').innerText()).includes('m'));
  await page.screenshot({ path: path.join(output, '13-measurement.png') });
  await page.locator('#clear-measure-button').click();
  await page.locator('#measure-dialog [data-dialog-close]').click();
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export-button').click();
  const download = await downloadPromise;
  const file = path.join(output, 'verified-export.json');
  await download.saveAs(file);
  const exported = await (await fetch(`${base}/api/export`)).json();
  assert.ok(exported.provenance.manifest_source);
  assert.ok(Object.keys(exported.provenance.source_record).length > 3);
  await page.locator('#reset-view-button').click();
  await until(s => !s.renderer.selected);
  await page.locator('.right-sidebar').evaluate(element => { element.scrollTop = 0; });
  await page.mouse.move(1100, 50);
  await page.waitForTimeout(4000);
  await page.screenshot({ path: path.join(output, '14-delivery.png') });
  await writeFile(path.join(output, 'measurement.json'), JSON.stringify({ passed: true, distance_m: measured.renderer.measurement.distance_m, points: measured.renderer.measurement.points, provenance: true }, null, 2));
  console.log(JSON.stringify({ passed: true, distance_m: measured.renderer.measurement.distance_m, provenance: true }));
} finally { await browser.close(); }
