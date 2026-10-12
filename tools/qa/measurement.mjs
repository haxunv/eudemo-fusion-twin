import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1, acceptDownloads: true });
async function until(predicate, label) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    const s = await snapshot();
    assert.ok(!s.renderer.error, s.renderer.error);
    if (predicate(s) && s.renderer.ready && s.renderer.server_epoch === s.server_epoch &&
        s.renderer.applied_revision === s.revision && s.field_ref?.key &&
        s.renderer.applied_field_key === s.field_ref.key) return s;
    await page.waitForTimeout(100);
  }
  throw new Error(`Renderer state did not settle: ${label}: ${JSON.stringify(await snapshot())}`);
}
async function uiCommand(type, trigger) {
  const responsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/action' && response.request().method() === 'POST' &&
    response.request().postDataJSON()?.type === type);
  await trigger();
  const response = await responsePromise;
  assert.ok(response.ok(), `${type}: ${response.status()} ${await response.text()}`);
  return complete((await response.json()).request_id);
}
async function surfaceClick(x, y) {
  const box = await page.locator('video').boundingBox();
  const aspect = await page.locator('video').evaluate(video => video.videoWidth / video.videoHeight);
  const width = Math.min(box.width, box.height * aspect);
  const height = width / aspect;
  await page.mouse.click(box.x + (box.width - width) / 2 + x * width, box.y + (box.height - height) / 2 + y * height);
}
try {
  const manifestResponse = await fetch(`${base}/api/manifest`);
  assert.ok(manifestResponse.ok);
  const manifest = await manifestResponse.json();
  const initial = {
    design: 'conventional', equilibrium: 'reference', language: 'zh', view: 'overview', tab: 'explore',
    mode: 'assembly', scenario: 'nominal', power: 2000, flow: 1, inlet: 300, phase: 0.65,
    cutaway: 80, explode: 0, opacity: 1, selected: '', fieldLines: false, orbit: false, playing: false,
    visible: Object.fromEntries(manifest.components.map(component => [component.id, component.default_visible !== false])),
  };
  await post('state', initial);
  await until(s => Object.entries(initial).every(([key, value]) => key === 'visible'
    ? Object.entries(value).every(([id, visible]) => s.state.visible[id] === visible)
    : s.state[key] === value), 'explicit conventional/reference nominal starting state');
  await complete((await post('action', { type: 'measure_clear' })).request_id);
  await complete((await post('action', { type: 'reset_camera', view: 'overview' })).request_id);
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 30000 });
  await uiCommand('reset_camera', () => page.locator('#reset-view-button').click());
  await until(s => s.state.mode === 'assembly' && s.state.selected === '' && !s.renderer.selected, 'overview camera and selection reset');
  await page.locator('[data-tab="engineering"]').click();
  await page.locator('#measure-button').evaluate(element => {
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
  });
  await page.locator('#measure-button').click();
  await uiCommand('measure_start', () => page.locator('#start-measure-button').click());
  await page.locator('#measure-dialog').waitFor({ state: 'hidden' });
  await until(s => !s.renderer.measurement, 'measurement initialized');
  const normalizedPoints = [[0.405, 0.42], [0.43, 0.50]];
  await uiCommand('measure', () => surfaceClick(...normalizedPoints[0]));
  await until(s => s.renderer.measurement?.type === 'point', 'first CAD surface hit');
  await uiCommand('measure', () => surfaceClick(...normalizedPoints[1]));
  const measured = await until(s => s.renderer.measurement?.type === 'distance', 'second CAD surface hit and distance');
  assert.ok(measured.renderer.measurement.distance_m > 1);
  const points = measured.renderer.measurement.points;
  assert.equal(points.length, 2);
  assert.ok(points.every(point => point.length === 3 && point.every(Number.isFinite)));
  const geometricDistance = Math.hypot(...points[0].map((value, axis) => value - points[1][axis]));
  assert.ok(Math.abs(geometricDistance - measured.renderer.measurement.distance_m) < 0.0001);
  await page.locator('#measure-dialog').waitFor({ state: 'visible' });
  assert.ok((await page.locator('.measure-result').innerText()).includes('m'));
  await page.screenshot({ path: path.join(output, '13-measurement.png') });
  await uiCommand('measure_clear', () => page.locator('#clear-measure-button').click());
  await until(s => !s.renderer.measurement, 'measurement cleared');
  await page.waitForFunction(() => !document.querySelector('#measure-button').classList.contains('active'));
  await page.locator('#measure-dialog [data-dialog-close]').click();
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export-button').click();
  const download = await downloadPromise;
  const file = path.join(output, 'verified-export.json');
  await download.saveAs(file);
  const exported = JSON.parse(await readFile(file, 'utf8'));
  assert.ok(exported.provenance.manifest_source);
  assert.ok(Object.keys(exported.provenance.source_record).length > 3);
  assert.equal(exported.state.design, initial.design);
  assert.equal(exported.state.equilibrium, initial.equilibrium);
  assert.equal(exported.field_ref.key, exported.result.field_ref.key);
  assert.equal(exported.field_ref.key, measured.field_ref.key);
  await uiCommand('reset_camera', () => page.locator('#reset-view-button').click());
  await until(s => !s.renderer.selected && s.state.selected === '', 'final camera and selection reset');
  await page.locator('.right-sidebar').evaluate(element => { element.scrollTop = 0; });
  await page.mouse.move(1100, 50);
  await page.waitForTimeout(4000);
  await page.screenshot({ path: path.join(output, '14-delivery.png') });
  await writeFile(path.join(output, 'measurement.json'), JSON.stringify({ passed: true, base, initial, normalizedPoints, distance_m: measured.renderer.measurement.distance_m, points, field_ref: measured.field_ref, provenance: true }, null, 2));
  console.log(JSON.stringify({ passed: true, distance_m: measured.renderer.measurement.distance_m, provenance: true }));
} finally { await browser.close(); }
