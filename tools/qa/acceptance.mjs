import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
await mkdir(output, { recursive: true });
const checks = [], errors = [], failedRequests = [];
const headless = process.env.QA_HEADLESS !== '0';
const captureUI = process.env.QA_CAPTURE_UI !== '0';
const label = process.env.QA_LABEL || '';
if (label) assert.match(label, /^[a-zA-Z0-9_-]+$/);
const reportPath = path.join(output, `acceptance${label ? `-${label}` : ''}.json`);
const videoMetrics = { method: 'requestVideoFrameCallback presentation callbacks',
  fullWorkflow: null, steady: null, captures: [] };
let videoStart = null, videoEnd = null;
const browser = await chromium.launch({channel:'msedge',headless,args:['--autoplay-policy=no-user-gesture-required','--no-proxy-server']});
const context = await browser.newContext({viewport:{width:1600,height:1000},deviceScaleFactor:1,acceptDownloads:true});
const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => {
  if (message.type() === 'error') {
    const {url, lineNumber} = message.location();
    errors.push(message.text() + (url ? ` (${url}:${lineNumber})` : ''));
  }
});
page.on('requestfailed', request => failedRequests.push({url: request.url(),
  method: request.method(), error: request.failure()?.errorText}));
async function waitState(predicate,label) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    const s = await snapshot();
    assert.ok(!s.renderer.error, s.renderer.error);
    if (predicate(s) && s.renderer.ready && s.renderer.server_epoch === s.server_epoch &&
        s.renderer.applied_revision === s.revision && s.field_ref?.key &&
        s.renderer.applied_field_key === s.field_ref.key) {
      assert.equal(s.renderer.render_mode, 'RealTimePathTracing', `All live modes must use RT2: ${label}`);
      assert.match(s.renderer.engine, /RTX Real-Time 2\.0/);
      checks.push(label);
      return s;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`State did not settle: ${label}: ${JSON.stringify(await snapshot())}`);
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
async function slider(id,value){await page.locator(id).evaluate((e,v)=>{e.value=String(v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));},value);}
async function capture(name) {
  const before = await videoSample();
  await page.waitForTimeout(800);
  const beforeScreenshot = await videoSample();
  const screenshotStart = performance.now();
  if (captureUI) await page.screenshot({ path: path.join(output, name) });
  const screenshotDurationMs = performance.now() - screenshotStart;
  const after = await videoSample();
  videoMetrics.captures.push({ name, captured: captureUI, waitMs: 800, screenshotDurationMs,
    fullInterval: videoDifference(before, after), waitInterval: videoDifference(before, beforeScreenshot),
    screenshotInterval: videoDifference(beforeScreenshot, after), before, beforeScreenshot, after });
}
async function videoSample() {
  return page.locator('video').evaluate(video => {
    const quality = video.getVideoPlaybackQuality();
    return { width: video.videoWidth, height: video.videoHeight, time: performance.now(),
      presented: window.__acceptancePresented, frames: quality.totalVideoFrames,
      dropped: quality.droppedVideoFrames };
  });
}
function videoDifference(start, end) {
  const seconds = (end.time - start.time) / 1000;
  return { seconds, presentedFps: (end.presented - start.presented) / seconds,
    presentedFrames: end.presented - start.presented, totalVideoFrames: end.frames - start.frames,
    totalVideoFramesFps: (end.frames - start.frames) / seconds,
    dropped: end.dropped - start.dropped,
    droppedRate: (end.dropped - start.dropped) / Math.max(1, end.frames - start.frames) };
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
  await waitState(s => Object.entries(initial).every(([key, value]) => key === 'visible'
    ? Object.entries(value).every(([id, visible]) => s.state.visible[id] === visible)
    : s.state[key] === value), 'explicit conventional/reference nominal starting state');
  await complete((await post('action', { type: 'measure_clear' })).request_id);
  await complete((await post('action', { type: 'reset_camera', view: 'overview' })).request_id);
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('video').readyState===4,{},{timeout:30000});
  await page.locator('video').evaluate(video => {
    window.__acceptancePresented = 0;
    const frame = () => { window.__acceptancePresented++; video.requestVideoFrameCallback(frame); };
    video.requestVideoFrameCallback(frame);
  });
  await page.waitForTimeout(2500);
  videoStart=await videoSample();
  const expectedResolution=(await snapshot()).renderer.resolution;
  assert.deepEqual([videoStart.width,videoStart.height],expectedResolution,'Decoded WebRTC dimensions must match the renderer');checks.push(`real RTX WebRTC ${videoStart.width}x${videoStart.height}`);
  await capture('02-overview-zh.png');
  await page.locator('[data-lang="en"]').click();
  await page.waitForFunction(()=>document.documentElement.lang==='en');
  assert.match(await page.title(),/Fusion Digital Twin/);checks.push('English localization');
  await page.locator('#assembly-button').click();
  await page.locator('[data-component="blanket"]').click();
  await waitState(s=>s.state.selected==='blanket','CAD component selection');
  await page.locator('[data-visible="blanket"]').uncheck();
  await waitState(s=>s.state.visible.blanket===false,'component hide');
  await page.locator('[data-visible="blanket"]').check();
  await waitState(s=>s.state.visible.blanket===true,'component show');
  await page.locator('#isolate-button').click();
  await waitState(s=>Object.values(s.state.visible).filter(Boolean).length===1&&s.state.visible.blanket,'component isolation');
  await page.locator('#component-measure').click();
  await page.locator('#measure-dialog').waitFor({state:'visible'});
  assert.equal(await page.locator('.dimension-cards strong').count(),3);checks.push('CAD dimensions dialog');
  await page.locator('#measure-dialog [data-dialog-close]').click();
  await uiCommand('reset_camera', () => page.locator('#reset-view-button').click());
  await waitState(s=>s.state.visible.plasma&&!s.state.visible.cryostat,'restore default assembly');
  await capture('03-assembly-en.png');
  await page.locator('[data-close="assembly-drawer"]').click();
  await slider('#cutaway-range',140);
  await waitState(s=>s.state.cutaway===140,'CAD sector cutaway');
  await slider('#explode-range',0.4);
  await waitState(s=>s.state.explode===0.4,'CAD exploded assembly');
  await capture('04-exploded.png');
  await uiCommand('reset_camera', () => page.locator('#reset-view-button').click());
  await waitState(s=>s.state.explode===0&&s.state.cutaway===80,'reset transformations');
  await page.locator('[data-mode="temperature"]').click();
  const nominal=await waitState(s=>s.state.mode==='temperature','temperature surface mode');
  await page.locator('#scenario-select').selectOption('highload');
  const hot=await waitState(s=>s.state.scenario==='highload'&&s.state.power===2400,'high thermal load scenario');
  assert.ok(hot.result.peak_temperature_C>nominal.result.peak_temperature_C);assert.ok(hot.result.gpu_device.startsWith('cuda'));checks.push('real CUDA scenario response');
  await capture('05-temperature-highload.png');
  await page.locator('[data-tab="compare"]').click();
  await waitState(s=>s.state.tab==='compare','comparison tab');
  assert.ok(hot.result.comparison.delta.peak_temperature_C>0);checks.push('reference/current delta');
  await capture('06-comparison.png');
  await page.locator('[data-tab="explore"]').click();
  await waitState(s=>s.state.tab==='explore','exploration restore');
  await page.locator('[data-mode="magnetic"]').click();
  await waitState(s=>s.state.mode==='magnetic','equilibrium magnetic lines mode');
  await capture('07-magnetic.png');
  await page.locator('[data-mode="slice"]').click();
  await page.locator('[data-view="section"]').click();
  await waitState(s=>s.state.mode==='slice'&&s.state.view==='section','plasma section mode and camera');
  await capture('08-slice.png');
  await page.locator('[data-mode="heatflux"]').click();
  await waitState(s=>s.state.mode==='heatflux','heat flux surface mode');
  await slider('#phase-range',0.2);
  const scanStart=await waitState(s=>!s.state.playing&&s.state.phase===0.2,'load scan starts at a defined position');
  await page.locator('#play-button').click();
  await waitState(s=>s.state.playing,'quasi-steady load scan play');
  await waitState(s=>s.state.playing&&s.revision>scanStart.revision&&
    ((s.state.phase-scanStart.state.phase+1)%1)>0.001,'quasi-steady load scan advances across wraparound');
  await page.locator('#play-button').click();
  const paused=await waitState(s=>!s.state.playing,'quasi-steady load scan pause');
  const exportPromise=page.waitForEvent('download');
  await page.locator('#export-button').click();
  const exportFile=await exportPromise;
  const exportPath=path.join(output,'exported-scenario.json');
  await exportFile.saveAs(exportPath);
  const exported=JSON.parse(await readFile(exportPath,'utf8'));
  assert.equal(exported.field_ref.key,paused.field_ref.key);
  assert.equal(exported.result.field_ref.key,exported.field_ref.key);
  assert.equal(exported.state.design,'conventional');
  assert.equal(exported.state.equilibrium,'reference');
  checks.push('scenario JSON download matches applied field');
  const screenshotPromise=page.waitForEvent('download');
  const captured=await uiCommand('capture',()=>page.locator('#screenshot-button').click());
  assert.ok(captured.result?.capture_url);
  const screenshot=await screenshotPromise;
  const screenshotPath=path.join(output,'exported-rtx.png');
  await screenshot.saveAs(screenshotPath);
  const png=await readFile(screenshotPath);
  assert.deepEqual([...png.subarray(0,8)],[137,80,78,71,13,10,26,10]);
  assert.deepEqual([png.readUInt32BE(16),png.readUInt32BE(20)],expectedResolution);
  const capturedResponse=await fetch(new URL(captured.result.capture_url,base));
  assert.ok(capturedResponse.ok);
  assert.deepEqual(png,Buffer.from(await capturedResponse.arrayBuffer()));
  checks.push('completed native RTX capture downloaded at renderer resolution');
  await page.locator('#provenance-button').click();
  await page.locator('#provenance-dialog').waitFor({state:'visible'});
  assert.match(await page.locator('#provenance-dialog').innerText(),/synthetic|Synthetic|simplified/i);checks.push('data provenance disclosure');
  await page.locator('#provenance-dialog [data-dialog-close]').click();
  for (const kind of ['cad', 'usd']) {
    const response = await fetch(`${base}/api/download/${kind}.zip`);
    assert.equal(response.status, 200);
    const archive = Buffer.from(await response.arrayBuffer());
    assert.ok(archive.length > 1000000);
    assert.equal(archive.length, Number(response.headers.get('content-length')));
    assert.deepEqual(archive, await readFile(new URL(`../../assets/downloads/${kind}.zip`, import.meta.url)));
    checks.push(`${kind.toUpperCase()} complete asset ZIP`);
  }
  const invalid=await fetch(`${base}/api/state`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({power:-1})});
  await invalid.arrayBuffer();
  assert.equal(invalid.status,400);checks.push('invalid state rejected');
  await page.locator('[data-mode="assembly"]').click();
  await page.locator('#scenario-select').selectOption('nominal');
  await uiCommand('reset_camera', () => page.locator('#reset-view-button').click());
  await slider('#phase-range',0.65);
  await page.locator('[data-lang="zh"]').click();
  await waitState(s=>s.state.mode==='assembly'&&s.state.scenario==='nominal'&&s.state.view==='overview'&&s.state.phase===0.65,'default view restored');
  await capture('09-final-zh.png');
  videoEnd=await videoSample();
  videoMetrics.fullWorkflow = { ...videoDifference(videoStart, videoEnd), start: videoStart, end: videoEnd,
    diagnosticOnly: captureUI, targetPresentedFps: captureUI ? null : 24, maxDroppedRate: captureUI ? null : 0.05,
    excludedIntervals: [], workload: 'All functional checks, mode switches, shader compilation, geometry selection/hide/isolate/cutaway/explode, optional UI screenshots, native capture and exports' };
  await waitState(s => s.state.mode === 'assembly' && !s.state.orbit && !s.state.playing &&
    s.renderer.quality === 'detail' && s.renderer.render_mode === 'RealTimePathTracing' &&
    !s.renderer.current_command && !s.renderer.capture_pending, 'final renderer settled to RT2 detail');
  const warmupMs = 12000, windowMs = 6000;
  await page.waitForTimeout(warmupMs);
  const rendererBefore = (await snapshot()).renderer;
  const steadyStart = await videoSample();
  // Fixed idle window: no UI actions, screenshots, exports or pixel readbacks.
  await page.waitForTimeout(windowMs);
  const steadyEnd = await videoSample();
  const rendererAfter = (await snapshot()).renderer;
  videoMetrics.steady = { ...videoDifference(steadyStart, steadyEnd), warmupMs, windowMs,
    targetPresentedFps: 24, start: steadyStart, end: steadyEnd,
    rendererBefore, rendererAfter };
  const fps=videoMetrics.steady.presentedFps;
  assert.equal(rendererBefore.render_mode, 'RealTimePathTracing');
  assert.equal(rendererAfter.render_mode, 'RealTimePathTracing');
  assert.match(rendererBefore.engine, /RTX Real-Time 2\.0/);
  assert.match(rendererAfter.engine, /RTX Real-Time 2\.0/);
  assert.equal(rendererAfter.quality, 'detail');
  assert.equal(rendererAfter.applied_revision, rendererBefore.applied_revision);
  assert.deepEqual([steadyEnd.width, steadyEnd.height], expectedResolution);
  assert.ok(fps>=24, `Steady presentation below 24 FPS: ${fps}; full workflow diagnostic: ${videoMetrics.fullWorkflow.presentedFps}`);
  checks.push('fixed steady window presents at least 24fps');
  if (!captureUI) {
    assert.ok(videoMetrics.fullWorkflow.presentedFps >= 24,
      `Full functional workflow presentation below 24 FPS: ${videoMetrics.fullWorkflow.presentedFps}`);
    assert.ok(videoMetrics.fullWorkflow.droppedRate <= 0.05,
      `Full functional workflow dropped more than 5% of video frames: ${videoMetrics.fullWorkflow.droppedRate}`);
    checks.push('complete functional workflow presents at least 24fps with at most 5% drops');
  }
  assert.deepEqual(errors,[]);checks.push('no browser JavaScript errors');
  await writeFile(reportPath,JSON.stringify({passed:true,base,headless,captureUI,label,initial,checks,fps,videoMetrics,videoStart,videoEnd,errors,failedRequests,final:await snapshot()},null,2));
  console.log(JSON.stringify({passed:true,checks:checks.length,fps,captureUI,reportPath,fullWorkflowPresentedFps:videoMetrics.fullWorkflow.presentedFps,errors}));
} catch(error) {
  await writeFile(reportPath,JSON.stringify({passed:false,base,headless,captureUI,label,checks,errors,failedRequests,
    fps:videoMetrics.steady?.presentedFps,videoMetrics,videoStart,videoEnd,failure:error.stack,state:await snapshot()},null,2));
  if (captureUI) await page.screenshot({path:path.join(output,'failure.png')});
  throw error;
} finally {await browser.close();}
