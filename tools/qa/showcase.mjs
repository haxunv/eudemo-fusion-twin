/** New showcase UI: run serially with exclusive access to the live renderer. */
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
const checks = [], errors = [], assets = [], layouts = [];
const report = { passed: false, checks, errors, assets, layouts,
  scope: 'Real UI writes, applied renderer snapshots, decoded video readiness and DOM/legend semantics. Mode pixels require the saved visual evidence to be reviewed.' };
const original = (await snapshot()).state;
const browser = await chromium.launch({ channel: 'msedge', headless: process.env.QA_HEADLESS !== '0',
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('pageerror', error => errors.push(String(error)));
const check = (name, evidence) => { checks.push({ name, evidence }); console.log(name); };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function toggleInput(page, selector, checked) {
  const input = page.locator(selector);
  if (await input.isChecked() !== checked) await input.locator('xpath=..').click();
  assert.equal(await input.isChecked(), checked, selector);
}
async function settled(expected) {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    const s = await snapshot(), r = s.renderer;
    assert.ok(!r.error, r.error);
    assert.ok(!r.volume_error, r.volume_error);
    if (r.ready && r.server_epoch === s.server_epoch && r.applied_revision === s.revision &&
        r.applied_field_key === s.field_ref?.key && Object.entries(expected).every(([key, value]) => s.state[key] === value) &&
        (s.state.mode !== 'volume' || (!r.volume_pending && r.applied_volume_field_key === s.field_ref.key &&
          r.volume_mask_angle === s.state.cutaway && r.volume_style === s.state.volumeStyle))) return s;
    await delay(100);
  }
  throw new Error(`Showcase state did not settle: ${JSON.stringify(expected)}`);
}
async function tab(name) {
  await page.locator(`[data-tab="${name}"]`).click();
  await settled({ tab: name });
  await page.locator(`#${name}-panel`).waitFor({ state: 'visible' });
}
async function mode(name) {
  await page.locator(`[data-mode="${name}"]`).click();
  return settled({ mode: name });
}
async function metric(s) {
  const selected = s.result.story.cases.find(item => item.id === s.result.story.selected_case_id);
  assert.ok(selected);
  await page.waitForFunction(({ peak, relative }) => {
    const numeric = id => Number(document.querySelector(id).textContent.replace(/[,%+]/g, ''));
    return Math.abs(numeric('#story-peak') - peak) <= .011 && Math.abs(numeric('#story-relative') - relative) <= .051;
  }, { peak: selected.peak_divertor_heatflux_MW_m2, relative: selected.relative_no_neon_percent });
  return selected;
}
async function layout(name) {
  const evidence = await page.evaluate(() => {
    const visible = element => element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    const rect = element => { const b = element.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height, right: b.right, bottom: b.bottom }; };
    const identify = element => element.id || element.dataset.i18n || element.dataset.mode || element.dataset.heating || element.tagName;
    const clipped = element => {
      const b = rect(element);
      if (b.x < -1 || b.y < -1 || b.right > innerWidth + 1 || b.bottom > innerHeight + 1) return true;
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent), p = rect(parent);
        if (/(auto|scroll|hidden|clip)/.test(style.overflowY) && (b.y < p.y - 1 || b.bottom > p.bottom + 1)) return true;
        if (/(auto|scroll|hidden|clip)/.test(style.overflowX) && (b.x < p.x - 1 || b.right > p.right + 1)) return true;
      }
      return false;
    };
    const selectors = ['.mode-tabs', '.views-panel', '.equilibrium-nav', '.hero-readout', '.visualization-panel',
      '[data-heating]', '.neon-control', '[data-design]', '[data-case-design]', '#mode-buttons button',
      '#heat-options', '#volume-options', '#magnetic-options', '#field-legend', '#reset-view-button'];
    const controls = [...new Set(selectors.flatMap(selector => [...document.querySelectorAll(selector)]))]
      .filter(visible).map(element => ({ name: identify(element), rect: rect(element), clipped: clipped(element) }));
    const text = [...document.querySelectorAll('body *')].filter(element => visible(element) &&
      [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()))
      .map(element => ({ name: identify(element), text: element.textContent.trim().slice(0, 90), font: parseFloat(getComputedStyle(element).fontSize) }));
    const body = document.querySelector('.sidebar-body');
    return { language: document.documentElement.lang, viewport: [innerWidth, innerHeight],
      sidebar: { clientHeight: body.clientHeight, scrollHeight: body.scrollHeight, scrollTop: body.scrollTop },
      controls, minimumFont: Math.min(...text.map(item => item.font)), undersized: text.filter(item => item.font < 12),
      untranslated: [...document.querySelectorAll('[data-i18n]')].filter(visible).filter(element => !element.textContent.trim() || element.textContent.trim() === element.dataset.i18n).map(identify),
      pageOverflow: document.documentElement.scrollHeight > innerHeight || document.documentElement.scrollWidth > innerWidth };
  });
  layouts.push({ name, ...evidence });
  assert.deepEqual(evidence.viewport, [1920, 1080]);
  assert.equal(evidence.pageOverflow, false, name);
  assert.ok(evidence.sidebar.scrollHeight <= evidence.sidebar.clientHeight + 1, `${name}: primary controls need scrolling: ${JSON.stringify(evidence.sidebar)}`);
  assert.ok(evidence.sidebar.scrollTop <= 1, `${name}: primary panel starts scrolled`);
  assert.deepEqual(evidence.controls.filter(item => item.clipped), [], `${name}: clipped controls`);
  assert.deepEqual(evidence.undersized, [], `${name}: text under 12px`);
  assert.deepEqual(evidence.untranslated, [], `${name}: missing localization`);
  check(`layout_${name}`, { minimumFont: evidence.minimumFont, sidebar: evidence.sidebar, controls: evidence.controls.length });
}
async function capture(name) {
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${output}/showcase-${name}.png` });
}
try {
  const manifestResponse = await fetch(`${base}/api/manifest`);
  assert.ok(manifestResponse.ok);
  const manifest = await manifestResponse.json();
  await post('state', { tab: 'explore', design: 'conventional', equilibrium: 'sof', scenario: 'nominal',
    heating: 50, neon: false, power: 2000, flow: 1, inlet: 300, phase: 1,
    mode: 'volume', volumeStyle: 'plasma', heatScale: 'log', lineMotion: true,
    view: 'overview', cutaway: 80, explode: 0, opacity: 1, selected: '', fieldLines: false,
    orbit: false, playing: false, visible: Object.fromEntries(manifest.components.map(item => [item.id, item.default_visible !== false])) });
  await settled({ mode: 'volume', volumeStyle: 'plasma', equilibrium: 'sof' });
  await complete((await post('action', { type: 'reset_camera', view: 'overview' })).request_id);
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('#remote-video').readyState === 4 &&
    window.FusionStreamer?.connected && document.querySelector('#viewport').classList.contains('live'), {}, { timeout: 60000 });
  const decoded = await page.locator('#remote-video').evaluate(video => [video.videoWidth, video.videoHeight]);
  assert.deepEqual(decoded, (await snapshot()).renderer.resolution);
  check('real_video_connected', decoded);

  for (const family of [['cameras', ['overview', 'front', 'top', 'section', 'divertor']], ['designs', ['conventional', 'longleg']]]) {
    for (const name of family[1]) {
      const source = `/assets/ui/${family[0]}/${name}.png`;
      const image = page.locator(`img[src="${source}"]`);
      await image.waitFor({ state: 'visible' });
      await image.evaluate(element => element.decode());
      const dimensions = await image.evaluate(element => [element.naturalWidth, element.naturalHeight]);
      assert.ok(dimensions[0] >= 128 && dimensions[1] >= 64, `${source}: actual raster thumbnail required`);
      const response = await fetch(`${base}${source}`);
      assert.ok(response.ok, source);
      const bytes = Buffer.from(await response.arrayBuffer());
      assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
      assets.push({ source, dimensions, sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length });
    }
  }
  for (const [family, count] of [['cameras', 5], ['designs', 2]]) {
    assert.equal(new Set(assets.filter(item => item.source.includes(`/${family}/`)).map(item => item.sha256)).size, count, `${family}: distinct views required`);
  }
  const provenanceResponse = await fetch(`${base}/assets/ui/manifest.json`);
  assert.ok(provenanceResponse.ok, 'RTX thumbnail provenance manifest');
  const provenance = await provenanceResponse.json();
  assert.match(provenance.scene_sha256, /^[a-f0-9]{64}$/);
  for (const asset of assets) {
    const card = provenance.cards.find(item => item.path === asset.source.replace('/assets/ui/', ''));
    assert.ok(card, `Missing RTX provenance: ${asset.source}`);
    assert.equal(card.source, 'native RTX capture');
    assert.equal(card.sha256, asset.sha256);
    assert.equal(typeof card.capture_request_id, 'string');
    assert.ok(card.capture_request_id.length > 0);
    assert.ok(card.field_ref?.key);
    assert.match(card.renderer, /RTX/);
    asset.captureRequestId = card.capture_request_id;
    asset.fieldKey = card.field_ref.key;
  }
  report.thumbnailSceneSHA256 = provenance.scene_sha256;
  check('five_camera_and_two_design_native_rtx_images', assets);

  for (const language of ['zh', 'en']) {
    await page.locator(`[data-lang="${language}"]`).click();
    await page.waitForFunction(value => document.documentElement.lang === value, language === 'zh' ? 'zh-CN' : 'en');
    assert.equal(await page.locator('[data-i18n="heating"]').innerText(), language === 'zh' ? '辅助加热' : 'Auxiliary heating');
    for (const viewMode of ['assembly', 'heatflux', 'magnetic', 'volume']) {
      await mode(viewMode);
      await layout(`${language}-${viewMode}`);
    }
    await capture(`${language}-plasma`);
  }

  await mode('heatflux');
  const heatingEvidence = [];
  for (const heating of [20, 35, 50, 65]) {
    await page.locator(`[data-heating="${heating}"]`).click();
    const s = await settled({ heating });
    const current = await metric(s);
    assert.equal(current.heating, heating);
    assert.deepEqual(s.result.color_ranges.heatflux, [0, 200]);
    assert.deepEqual(s.result.color_ranges.heatflux_log, [.01, 200]);
    heatingEvidence.push({ heating, peak: current.peak_divertor_heatflux_MW_m2, field: s.field_ref.key });
  }
  assert.equal(new Set(heatingEvidence.map(item => item.field)).size, 4);
  assert.ok(heatingEvidence.every((item, index) => !index || item.peak > heatingEvidence[index - 1].peak));
  check('four_heating_inputs_change_actual_fields', heatingEvidence);

  const designs = [];
  for (const design of ['conventional', 'longleg']) {
    await page.locator(`[data-design="${design}"]`).click();
    await settled({ design });
    await toggleInput(page, '#neon-toggle', false);
    const off = await settled({ design, neon: false });
    await metric(off);
    await toggleInput(page, '#neon-toggle', true);
    const on = await settled({ design, neon: true });
    const current = await metric(on);
    assert.notEqual(on.field_ref.key, off.field_ref.key);
    assert.ok(current.peak_divertor_heatflux_MW_m2 < off.result.peak_divertor_heatflux_MW_m2);
    assert.ok(current.relative_no_neon_percent < 0);
    assert.ok(on.field_ref.topology_key.startsWith(design));
    designs.push({ design, off: off.result.peak_divertor_heatflux_MW_m2, on: current.peak_divertor_heatflux_MW_m2, relative: current.relative_no_neon_percent });
  }
  check('two_designs_and_neon_cooling', designs);
  for (const scale of ['linear', 'log']) {
    await page.locator(`[data-heat-scale="${scale}"]`).click();
    const s = await settled({ heatScale: scale });
    const key = scale === 'log' ? 'heatflux_log' : 'heatflux';
    await page.waitForFunction(minimum => Number(document.querySelector('#legend-ticks span').textContent.replace(',', '')) === minimum, s.result.color_ranges[key][0]);
    assert.equal(await page.locator('#legend-unit').innerText(), 'MW/m²');
    assert.equal(s.result.color_maps.heatflux.name, 'inferno_sampled');
    check(`fixed_${scale}_legend`, { range: s.result.color_ranges[key], colors: s.result.color_maps.heatflux });
  }
  await capture('en-heatflux');

  await tab('compare');
  assert.equal(await page.locator('#comparison-cases .case-card').count(), 4);
  let comparison = await snapshot();
  assert.equal(comparison.result.story.cases.length, 4);
  for (const item of comparison.result.story.cases) {
    const card = page.locator(`[data-case-design="${item.design}"][data-case-neon="${item.neon}"]`);
    const value = Number((await card.locator('.case-value strong').innerText()).replaceAll(',', ''));
    assert.ok(Math.abs(value - item.peak_divertor_heatflux_MW_m2) <= .011);
    await card.click();
    const s = await settled({ design: item.design, neon: item.neon });
    await metric(s);
    assert.deepEqual(s.result.story.comparison_controls, comparison.result.story.comparison_controls);
  }
  for (const language of ['en', 'zh']) {
    await page.locator(`[data-lang="${language}"]`).click();
    await layout(`${language}-compare`);
  }
  check('four_case_cards_match_results_and_keep_controls', comparison.result.story);
  await capture('zh-compare');

  await tab('explore');
  const stageEvidence = [];
  for (const equilibrium of ['rampup', 'sof', 'eof', 'rampdown']) {
    await page.locator(`[data-equilibrium="${equilibrium}"]`).click();
    const s = await settled({ equilibrium, playing: false, phase: 1 });
    stageEvidence.push({ equilibrium, source: s.result.story.cases[0].source_equilibrium, key: s.field_ref.equilibrium_key });
  }
  assert.equal(new Set(stageEvidence.map(item => item.key)).size, 4);
  assert.match(await page.locator('[data-i18n="snapshotHint"]').innerText(), /独立源快照/);
  check('four_independent_source_snapshots', stageEvidence);
  await mode('magnetic');
  const magneticKey = (await snapshot()).field_ref.key;
  await toggleInput(page, '#line-motion-toggle', false);
  await settled({ lineMotion: false });
  await toggleInput(page, '#line-motion-toggle', true);
  const magnetic = await settled({ lineMotion: true });
  assert.equal(magnetic.field_ref.key, magneticKey);
  assert.equal(await page.locator('#legend-unit').innerText(), 'T');
  assert.match(await page.locator('#mode-note').innerText(), /不表示粒子速度/);
  check('magnetic_direction_semantics_and_cached_field', magnetic.field_ref.key);

  await page.locator('[data-equilibrium="sof"]').click();
  await settled({ equilibrium: 'sof' });
  await mode('volume');
  for (const language of ['zh', 'en']) {
    await page.locator(`[data-lang="${language}"]`).click();
    await page.locator('[data-volume-style="plasma"]').click();
    await settled({ volumeStyle: 'plasma' });
    await page.locator('#field-legend').waitFor({ state: 'hidden' });
    assert.match(await page.locator('#mode-note').innerText(), language === 'zh' ? /展示示意/ : /illustrative/);
    await page.locator('[data-volume-style="temperature"]').click();
    const s = await settled({ volumeStyle: 'temperature' });
    await page.locator('#field-legend').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#legend-unit').innerText(), 'keV');
    const ticks = await page.locator('#legend-ticks span').allTextContents();
    assert.deepEqual([Number(ticks[0]), Number(ticks.at(-1))], s.renderer.volume_colormap.domain);
    assert.match(await page.locator('#mode-note').innerText(), language === 'zh' ? /合成温度场/ : /Synthetic temperature/);
    await layout(`${language}-volume-temperature`);
  }
  check('plasma_illustration_and_quantitative_temperature_legends', true);
  await page.locator('[data-lang="zh"]').click();
  await page.locator('[data-volume-style="plasma"]').click();
  await settled({ volumeStyle: 'plasma' });
  await capture('final-zh');
  assert.deepEqual(errors, []);
  report.final = await snapshot();
  report.passed = true;
} catch (error) {
  report.failure = String(error.stack || error);
  await page.screenshot({ path: `${output}/showcase-failure.png` }).catch(() => {});
  throw error;
} finally {
  await writeFile(`${output}/showcase.json`, JSON.stringify(report, null, 2));
  await browser.close();
  await post('state', original);
}
