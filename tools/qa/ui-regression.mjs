import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/ui-regression.json', import.meta.url));
const original = (await snapshot()).state;
const checks = [], errors = [];
const browser = await chromium.launch({ channel: 'msedge', headless: process.env.QA_HEADLESS !== '0',
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on('pageerror', error => errors.push(String(error)));
async function settled(expected) {
  for (let attempt = 0; attempt < 450; attempt++) {
    const s = await snapshot();
    assert.ok(!s.renderer.error, s.renderer.error);
    if (Object.entries(expected).every(([k, v]) => s.state[k] === v) &&
        s.renderer.applied_revision === s.revision && s.renderer.applied_field_key === s.field_ref.key) return s;
    await page.waitForTimeout(100);
  }
  throw new Error(`State did not settle: ${JSON.stringify(expected)}`);
}
async function command(type, trigger) {
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/action' &&
    response.request().postDataJSON()?.type === type);
  await trigger();
  const response = await pending;
  assert.ok(response.ok(), `${response.status()}: ${response.ok() ? '' : await response.text()}`);
  return complete((await response.json()).request_id);
}
async function startMeasure() {
  await page.locator('[data-tab="engineering"]').click();
  await settled({ tab: 'engineering' });
  await page.locator('#measure-button').evaluate(element => {
    for (let p = element.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
  });
  await page.locator('#measure-button').click();
  await command('measure_start', () => page.locator('#start-measure-button').click());
  await page.waitForFunction(() => document.querySelector('#measure-button').classList.contains('active'));
}
async function assertNormalPicking(label) {
  await page.waitForFunction(() => !document.querySelector('#measure-button').classList.contains('active'));
  await page.waitForFunction(() => document.querySelector('#story-sync').classList.contains('synchronized'));
  const result = await command('pick', () => page.mouse.click(790, 470));
  assert.equal(result.status, 'completed');
  assert.notEqual((await snapshot()).renderer.measurement?.type, 'point');
  checks.push(label);
}
let passed = false;
try {
  await post('state', { ...original, design: 'conventional', equilibrium: 'reference', mode: 'assembly',
    view: 'overview', tab: 'explore', selected: '', fieldLines: false, orbit: false, playing: false });
  await settled({ design: 'conventional', equilibrium: 'reference', mode: 'assembly' });
  await complete((await post('action', { type: 'measure_clear' })).request_id);
  await complete((await post('action', { type: 'reset_camera', view: 'overview' })).request_id);
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('video').readyState === 4, {}, { timeout: 60000 });

  await startMeasure();
  await page.locator('[data-equilibrium="sof"]').click();
  await settled({ equilibrium: 'sof' });
  await assertNormalPicking('changing equilibrium exits measurement and the next surface click selects');
  await startMeasure();
  await page.locator('[data-tab="explore"]').click();
  await page.locator('[data-design="longleg"]').click();
  await settled({ design: 'longleg' });
  await assertNormalPicking('changing design exits measurement and the next surface click selects');

  await page.locator('[data-view="front"]').click();
  await settled({ view: 'front' });
  assert.equal(await page.locator('[data-view="front"]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('[data-view="overview"]').getAttribute('aria-pressed'), 'false');
  checks.push('camera visual and accessible selection agree');

  await page.locator('[data-tab="compare"]').click();
  await settled({ tab: 'compare' });
  const target = '[data-case-design="conventional"][data-case-neon="true"]';
  await page.locator(target).focus();
  await page.evaluate(() => { window.__focusedCase = document.activeElement; });
  await page.waitForTimeout(2400);
  assert.ok(await page.evaluate(() => document.activeElement === window.__focusedCase && window.__focusedCase.isConnected));
  checks.push('comparison card focus survives multiple state polls');
  await post('state', { heating: original.heating === 35 ? 50 : 35 });
  await page.waitForTimeout(1400);
  assert.ok(await page.evaluate(() => document.activeElement === window.__focusedCase && window.__focusedCase.isConnected));
  await page.keyboard.press('Enter');
  await settled({ design: 'conventional', neon: true });
  checks.push('comparison card retains focus through new results and Enter selects the case');
  assert.deepEqual(errors, []);
  passed = true;
  console.log(JSON.stringify({ passed, checks: checks.length, errors }));
} finally {
  await writeFile(output, JSON.stringify({ passed, checks, errors }, null, 2));
  await browser.close();
  await post('state', original);
}
