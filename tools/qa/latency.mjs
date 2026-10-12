/**
 * Real UI -> service acknowledgement -> Kit observation -> decoded RTX pixels.
 * Run only with the exclusive browser window: node tools/qa/latency.mjs
 * QA_LATENCY_SAMPLES=20 QA_LATENCY_TARGET_MS=300 QA_LABEL=current
 * The target applies to video response onset. Kit report observation is an upper
 * bound (the bridge publishes periodically), not a timestamp of USD application.
 */
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { base, snapshot, post, complete } from './api.mjs';

const output = fileURLToPath(new URL('../../runtime/qa/', import.meta.url));
const label = process.env.QA_LABEL || 'current';
assert.match(label, /^[a-zA-Z0-9_-]+$/);
const sampleCount = Number(process.env.QA_LATENCY_SAMPLES || 20);
const targetMs = Number(process.env.QA_LATENCY_TARGET_MS || 300);
assert.ok(Number.isInteger(sampleCount) && sampleCount >= 4 && sampleCount <= 30);
assert.ok(Number.isFinite(targetMs) && targetMs > 0);
const settings = { roi: { x: 0.18, y: 0.12, width: 0.50, height: 0.76 },
  width: 192, height: 144, input: '#inlet-range', key: 'inlet', low: 200, high: 400,
  // Interior blanket patches in the fixed section camera, checked against saved ROI images.
  fixedRegions: [
    { id: 'left_blanket', x: 50, y: 30, width: 20, height: 55 },
    { id: 'right_blanket', x: 163, y: 30, width: 20, height: 55 },
  ],
  calibrationLimits: { minFieldPixels: 3000, minSignalMAE: 15, minPixelSignal: 10,
    minResponsiveFraction: .90, maxTemporalNoiseMAE: 2, minSignalToNoise: 8,
    returnMAEFloor: 3, maxReturnRatio: .15, returnPixelFloor: 6,
    maxPixelReturnRatio: .20, minReturnedFraction: .95 },
  frameSamples: 10, onsetFraction: 0.20, endpointFraction: 0.75,
  onsetFrames: 2, endpointFrames: 3, pollMs: 25, timeoutMs: 10000 };
const percentile = (values, q) => {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  return sorted.length ? sorted[Math.max(0, Math.ceil(sorted.length * q) - 1)] : null;
};
const summary = values => ({ count: values.filter(Number.isFinite).length,
  p50: percentile(values, .5), p95: percentile(values, .95), max: percentile(values, 1) });
await mkdir(output, { recursive: true });
const original = await snapshot();
const report = { passed: false, startedAt: new Date().toISOString(), targetMs, settings,
  units: 'milliseconds', inputMethod: 'DOM input event through the production slider handler',
  browserCompositing: 'default GPU', warmupTrialsExcluded: 2, warmupTrials: [], trials: [], errors: [], codeHashes: {},
  timingNotes: {
    service: 'Client receives committed-state acknowledgement over the actual UI transport; RTWT includes its HTTP relay.',
    kit: 'First HTTP observation of matching applied_field_key; periodic renderer reporting makes this an upper bound. It can arrive after visible pixels.',
    pixels: 'requestVideoFrameCallback samples decoded video pixels, excluding DOM overlays. First directionally correct colour change is confirmed over two frames. This is not a physical display/photodiode measurement.',
    calibration: 'Both fixed blanket patches and the full visible thermal mask must pass signal, temporal-noise and low/high/low return checks. The field mask is locked from the initial low image only; unresponsive or non-returning pixels are never removed. Trial onset and endpoint require every region.',
    workload: 'Warm engine and calibrated scene; distinct valid inlet steps request new parameter combinations. packetNewlyPublished reports whether the returned immutable packet was created by that commit.',
  } };
for (const name of ['web/app.js', 'app/fusion_twin/server.py', 'app/fusion_twin/compute.py',
  'kit/extensions/fusion.twin.bridge/fusion/twin/bridge/extension.py']) {
  report.codeHashes[name] = createHash('sha256').update(await readFile(new URL(`../../${name}`, import.meta.url))).digest('hex');
}
const browser = await chromium.launch({ channel: 'msedge', headless: process.env.QA_HEADLESS !== '0',
  args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('pageerror', error => report.errors.push(String(error)));

async function applied(expected) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    const state = await snapshot();
    assert.ok(!state.renderer.error, state.renderer.error);
    if (state.renderer.ready && state.renderer.server_epoch === state.server_epoch &&
        state.renderer.applied_field_key === state.field_ref.key && state.renderer.applied_revision === state.revision &&
        Object.entries(expected).every(([key, value]) => state.state[key] === value)) return state;
    await page.waitForTimeout(50);
  }
  throw new Error(`Renderer did not apply calibration state: ${JSON.stringify(expected)}`);
}

async function saveImages(images, prefix) {
  const paths = {};
  for (const [name, data] of Object.entries(images)) {
    if (!data) continue;
    const filename = `latency-${label}-${prefix}-${name}.png`;
    await writeFile(`${output}/${filename}`, Buffer.from(data.split(',')[1], 'base64'));
    paths[name] = filename;
  }
  return paths;
}

try {
  await post('state', { design: 'conventional', equilibrium: 'reference', scenario: 'nominal',
    mode: 'temperature', tab: 'engineering', view: 'section', power: 1500, flow: 1, inlet: settings.low,
    heating: 50, neon: false, heatScale: 'log', volumeStyle: 'plasma', lineMotion: false,
    phase: 1, cutaway: 80, explode: 0, opacity: 1, visible: { plasma: false },
    selected: '', fieldLines: false, orbit: false, playing: false });
  await applied({ mode: 'temperature', inlet: settings.low });
  await complete((await post('action', { type: 'reset_camera', view: 'section' })).request_id);
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('#remote-video')?.readyState === 4 &&
    window.FusionStreamer?.connected && document.querySelector('#viewport').classList.contains('live'), {}, { timeout: 60000 });
  await page.locator('#engineering-panel').waitFor({ state: 'visible' });
  const thermalControls = page.locator('#engineering-panel details').filter({ has: page.locator(settings.input) });
  if (!await thermalControls.evaluate(element => element.open)) await thermalControls.locator('summary').click();
  await page.locator(settings.input).scrollIntoViewIfNeeded();
  assert.ok(await page.locator(settings.input).isVisible(), 'Latency input must be a visible engineering control');
  report.browser = await browser.version();
  report.initial = await applied({ mode: 'temperature', inlet: settings.low });
  await page.waitForTimeout(8000);

  await page.evaluate(config => {
    const video = document.querySelector('#remote-video');
    if (!video.requestVideoFrameCallback) throw new Error('requestVideoFrameCallback is required');
    const canvas = document.createElement('canvas');
    canvas.width = config.width; canvas.height = config.height;
    const context = canvas.getContext('2d', { willReadFrequently: false });
    const nativeFetch = window.fetch.bind(window);
    const probe = window.__latency = { config, calibration: {}, active: null, mask: [] };
    const read = () => {
      const start = performance.now(), r = config.roi;
      context.drawImage(video, video.videoWidth * r.x, video.videoHeight * r.y,
        video.videoWidth * r.width, video.videoHeight * r.height, 0, 0, config.width, config.height);
      return { pixels: context.getImageData(0, 0, config.width, config.height).data,
        readMs: performance.now() - start };
    };
    const png = pixels => {
      context.putImageData(new ImageData(new Uint8ClampedArray(pixels), config.width, config.height), 0, 0);
      return canvas.toDataURL('image/png');
    };
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    const frame = () => new Promise((resolve, reject) => {
      const timer = setTimeout(() => { video.cancelVideoFrameCallback(id); reject(new Error('Live video stopped')); }, 3000);
      const id = video.requestVideoFrameCallback((now, metadata) => {
        clearTimeout(timer); resolve({ ...read(), now, metadata });
      });
    });
    const average = frames => {
      const result = new Float32Array(config.width * config.height * 4);
      for (const item of frames) for (let index = 0; index < result.length; index++) result[index] += item.pixels[index] / frames.length;
      return result;
    };
    const capture = async () => {
      const frames = [];
      for (let index = 0; index < config.frameSamples; index++) frames.push(await frame());
      return { frames, mean: average(frames) };
    };
    probe.calibrate = async name => {
      const value = await capture();
      probe.calibration[name] = value;
      return { image: png(value.mean), resolution: [video.videoWidth, video.videoHeight],
        readMs: value.frames.map(item => item.readMs) };
    };
    probe.prepare = () => {
      const a = probe.calibration.low, b = probe.calibration.high, c = probe.calibration.lowRepeat;
      const limits = config.calibrationLimits;
      const groups = config.fixedRegions.map(region => {
        const pixels = [];
        for (let y = region.y; y < region.y + region.height; y++) {
          for (let x = region.x; x < region.x + region.width; x++) pixels.push(y * config.width + x);
        }
        return { ...region, pixels };
      });
      // This includes every initially blue thermal pixel, regardless of its later response.
      const fieldPixels = [];
      for (let pixel = 0; pixel < config.width * config.height; pixel++) {
        const i = pixel * 4, red = a.mean[i], green = a.mean[i + 1], blue = a.mean[i + 2];
        if (blue > 110 && blue - red > 70 && blue - green > 30) fieldPixels.push(pixel);
      }
      groups.push({ id: 'visible_thermal_field', pixels: fieldPixels });
      probe.groups = groups;
      probe.mask = [...new Set(groups.flatMap(group => group.pixels))];
      const failures = [];
      const regions = groups.map(group => {
        let signal = 0, noise = 0, drift = 0, responsive = 0, returned = 0;
        const meanRGB = { low: [0, 0, 0], high: [0, 0, 0], lowRepeat: [0, 0, 0] };
        for (const pixel of group.pixels) {
          let pixelSignal = 0, pixelNoise = 0, pixelDrift = 0;
          for (let channel = 0; channel < 3; channel++) {
            const i = pixel * 4 + channel;
            pixelSignal += Math.abs(b.mean[i] - a.mean[i]) / 3;
            pixelDrift += Math.abs(c.mean[i] - a.mean[i]) / 3;
            for (const [name, capture] of [['low', a], ['high', b], ['lowRepeat', c]]) {
              meanRGB[name][channel] += capture.mean[i] / group.pixels.length;
              for (const sample of capture.frames) {
                pixelNoise += Math.abs(sample.pixels[i] - capture.mean[i]) / (9 * capture.frames.length);
              }
            }
          }
          signal += pixelSignal; noise += pixelNoise; drift += pixelDrift;
          if (pixelSignal >= Math.max(limits.minPixelSignal, limits.minSignalToNoise * pixelNoise)) responsive++;
          if (pixelDrift <= Math.max(limits.returnPixelFloor, limits.maxPixelReturnRatio * pixelSignal)) returned++;
        }
        const count = group.pixels.length, denominator = count || 1;
        const signalMAE = signal / denominator, temporalNoiseMAE = noise / denominator;
        const returnDriftMAE = drift / denominator;
        const returnMAELimit = Math.max(limits.returnMAEFloor, signalMAE * limits.maxReturnRatio);
        const checks = {
          coverage: count >= (group.id === 'visible_thermal_field' ? limits.minFieldPixels : group.width * group.height),
          signal: signalMAE >= Math.max(limits.minSignalMAE, temporalNoiseMAE * limits.minSignalToNoise),
          responsiveCoverage: responsive / denominator >= limits.minResponsiveFraction,
          temporalNoise: temporalNoiseMAE <= limits.maxTemporalNoiseMAE,
          returnMean: returnDriftMAE <= returnMAELimit,
          returnCoverage: returned / denominator >= limits.minReturnedFraction,
        };
        for (const [check, passed] of Object.entries(checks)) if (!passed) failures.push(`${group.id}: ${check}`);
        return { id: group.id, bounds: group.width ? [group.x, group.y, group.width, group.height] : null,
          pixels: count, signalMAE, temporalNoiseMAE, returnDriftMAE, returnMAELimit,
          returnDriftRatio: signalMAE ? returnDriftMAE / signalMAE : null,
          responsiveFraction: responsive / denominator, returnedFraction: returned / denominator,
          meanRGB, checks, passed: Object.values(checks).every(Boolean) };
      });
      const maskImage = new Uint8ClampedArray(config.width * config.height * 4);
      for (let i = 3; i < maskImage.length; i += 4) maskImage[i] = 255;
      for (const pixel of probe.mask) for (let channel = 0; channel < 3; channel++) maskImage[pixel * 4 + channel] = b.mean[pixel * 4 + channel];
      return { passed: failures.length === 0, failures, regions, selectedPixels: probe.mask.length,
        maskSelection: 'fixed blanket rectangles plus all initial-low blue field pixels; no response-based filtering',
        image: png(maskImage) };
    };

    const matches = patch => probe.active && Number(patch?.[config.key]) === probe.active.target;
    const request = window.FusionStreamer.request;
    window.FusionStreamer.request = async function (name, payload, timeout) {
      const trial = name === 'fusion_set_state' && matches(payload?.state) ? probe.active : null;
      if (trial) { trial.transport = 'rtwt-webrtc-http-relay'; trial.sentAt = performance.now(); trial.requestCount++; }
      try {
        const response = await request.call(this, name, payload, timeout);
        if (trial) {
          trial.ackAt = performance.now(); trial.acceptedRevision = response?.accepted_revision;
          if (!response?.accepted) trial.failure = response?.error || 'State change was rejected';
        }
        return response;
      } catch (error) { if (trial) trial.failure = String(error); throw error; }
    };
    window.fetch = async function (url, options) {
      let patch;
      if (options?.method === 'POST' && String(url).endsWith('/api/state')) {
        try { patch = JSON.parse(options.body); } catch { /* Other fetch bodies are unrelated. */ }
      }
      const trial = matches(patch) ? probe.active : null;
      if (trial) { trial.transport = 'http'; trial.sentAt = performance.now(); trial.requestCount++; }
      const response = await nativeFetch(url, options);
      if (trial) {
        const result = await response.clone().json();
        trial.ackAt = performance.now(); trial.acceptedRevision = result.revision;
        if (!response.ok) trial.failure = result.error || `HTTP ${response.status}`;
      }
      return response;
    };

    probe.run = async ({ target, previous, index }) => {
      if (document.hidden || video.paused || !window.FusionStreamer.connected) throw new Error('A foreground live video session is required');
      const baseline = await capture();
      const low = probe.calibration.low.mean, high = probe.calibration.high.mean;
      const fraction = (target - previous) / (config.high - config.low);
      const targetFraction = (target - config.low) / (config.high - config.low);
      const groups = probe.groups.map(group => {
        let energy = 0, signal = 0;
        for (const pixel of group.pixels) for (let channel = 0; channel < 3; channel++) {
          const i = pixel * 4 + channel, delta = (high[i] - low[i]) * fraction;
          energy += delta * delta; signal += Math.abs(delta);
        }
        return { ...group, energy, signal };
      });
      const score = pixels => {
        const regions = groups.map(group => {
          let projection = 0, targetError = 0;
          for (const pixel of group.pixels) for (let channel = 0; channel < 3; channel++) {
            const i = pixel * 4 + channel, delta = (high[i] - low[i]) * fraction;
            projection += (pixels[i] - baseline.mean[i]) * delta;
            targetError += Math.abs(pixels[i] - (low[i] + (high[i] - low[i]) * targetFraction));
          }
          return { id: group.id, progress: projection / group.energy, targetErrorRatio: targetError / group.signal };
        });
        return { progress: Math.min(...regions.map(region => region.progress)),
          targetErrorRatio: Math.max(...regions.map(region => region.targetErrorRatio)), regions };
      };
      const noise = Math.max(...baseline.frames.flatMap(item => score(item.pixels).regions.map(region => Math.abs(region.progress))));
      const threshold = Math.max(config.onsetFraction, noise * 8);
      if (threshold > .5) throw new Error(`Unstable video baseline: onset threshold ${threshold}`);
      const trial = probe.active = { index, target, previous, threshold, baselineNoise: noise,
        t0: performance.now(), requestCount: 0, frames: [], polls: [], lastNotAppliedAt: null };
      let finished = false, firstPixels, lastPixels, onsetCandidate, onsetCount = 0, endpointCandidate, endpointCount = 0;
      const poll = async () => {
        while (!finished) {
          const start = performance.now();
          try {
            const response = await nativeFetch('/api/state', { cache: 'no-store' });
            const state = await response.json(), now = performance.now();
            if (!response.ok || state.renderer.error) throw new Error(state.renderer.error || `HTTP ${response.status}`);
            const committed = state.state[config.key] === target;
            const applied = committed && state.renderer.server_epoch === state.server_epoch && state.renderer.applied_field_key === state.field_ref.key;
            trial.polls.push({ ms: now - trial.t0, roundTripMs: now - start, revision: state.revision,
              appliedRevision: state.renderer.applied_revision, committed, applied });
            if (committed && !trial.fieldReference) {
              trial.fieldReference = state.field_ref; trial.committedRevision = state.revision;
              trial.serverCommitObservedAt = now;
            }
            if (applied && !trial.kitObservedAt) {
              trial.kitObservedAt = now; trial.rendererReportAgeMs = state.renderer.heartbeat_age_s * 1000;
            } else if (!applied && !trial.kitObservedAt) trial.lastNotAppliedAt = now;
          } catch (error) { trial.failure = String(error); }
          await delay(config.pollMs);
        }
      };
      const polling = poll();
      const input = document.querySelector(config.input);
      input.value = String(target);
      if (Number(input.value) !== target) throw new Error(`Slider rejected value ${target}`);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      try {
        while (performance.now() - trial.t0 < config.timeoutMs) {
          const sample = await frame(), value = score(sample.pixels);
          lastPixels = sample.pixels;
          const displayedAt = sample.now;
          trial.frames.push({ ms: sample.now - trial.t0, displayMs: displayedAt - trial.t0,
            progress: value.progress, targetErrorRatio: value.targetErrorRatio, readMs: sample.readMs,
            regions: value.regions,
            mediaTime: sample.metadata.mediaTime, presentedFrames: sample.metadata.presentedFrames });
          if (value.progress >= threshold && value.targetErrorRatio < 1.1) {
            if (!onsetCount) onsetCandidate = displayedAt;
            onsetCount++;
            if (!trial.pixelOnsetAt && onsetCount >= config.onsetFrames) {
              trial.pixelOnsetAt = onsetCandidate; trial.pixelConfirmedAt = displayedAt;
              firstPixels = sample.pixels.slice();
            }
          } else onsetCount = 0;
          if (value.progress >= config.endpointFraction && value.targetErrorRatio < .65) {
            if (!endpointCount) endpointCandidate = displayedAt;
            endpointCount++;
            if (!trial.pixelEndpointAt && endpointCount >= config.endpointFrames) trial.pixelEndpointAt = endpointCandidate;
          } else endpointCount = 0;
          if (trial.failure) throw new Error(trial.failure);
          if (trial.ackAt && trial.kitObservedAt && trial.pixelOnsetAt && trial.pixelEndpointAt) {
            lastPixels = sample.pixels; break;
          }
        }
      } finally { finished = true; await polling; probe.active = null; }
      const elapsed = key => trial[key] == null ? null : trial[key] - trial.t0;
      return { index, target, previous, transport: trial.transport, requestCount: trial.requestCount,
        acceptedRevision: trial.acceptedRevision, fieldReference: trial.fieldReference,
        packetNewlyPublished: trial.fieldReference?.revision === trial.committedRevision,
        complete: Boolean(trial.ackAt && trial.kitObservedAt && trial.pixelOnsetAt && trial.pixelEndpointAt),
        debounceMs: elapsed('sentAt'), serviceAckMs: elapsed('ackAt'),
        serviceRoundTripMs: trial.ackAt - trial.sentAt,
        serverCommitObservedMs: elapsed('serverCommitObservedAt'), kitObservedMs: elapsed('kitObservedAt'),
        kitObservationIntervalMs: [elapsed('lastNotAppliedAt'), elapsed('kitObservedAt')],
        rendererReportAgeMs: trial.rendererReportAgeMs,
        videoOnsetMs: elapsed('pixelOnsetAt'), videoConfirmationMs: elapsed('pixelConfirmedAt'), videoEndpointMs: elapsed('pixelEndpointAt'),
        onsetThreshold: threshold, baselineNoise: noise, frames: trial.frames, polls: trial.polls,
        images: { before: png(baseline.mean), changed: firstPixels && png(firstPixels), settled: lastPixels && png(lastPixels) } };
    };
  }, settings);

  const calibration = report.calibration = {};
  for (const [name, value] of [['low', settings.low], ['high', settings.high], ['lowRepeat', settings.low]]) {
    await post('state', { inlet: value });
    const appliedState = await applied({ inlet: value });
    await page.waitForTimeout(3500);
    const item = await page.evaluate(name => window.__latency.calibrate(name), name);
    calibration[name] = { ...item, inlet: value, settleMs: 3500, fieldReference: appliedState.field_ref,
      appliedFieldKey: appliedState.renderer.applied_field_key, appliedRevision: appliedState.renderer.applied_revision,
      image: (await saveImages({ roi: item.image }, name)).roi };
  }
  const prepared = await page.evaluate(() => window.__latency.prepare());
  report.calibration = { ...calibration, ...prepared, image: (await saveImages({ mask: prepared.image }, 'calibration')).mask };
  assert.equal(calibration.low.fieldReference.key, calibration.lowRepeat.fieldReference.key,
    'Low-repeat calibration must use the identical immutable field packet');
  assert.notEqual(calibration.low.fieldReference.key, calibration.high.fieldReference.key,
    'High calibration must use a different field packet');
  assert.ok(prepared.passed, `Thermal calibration failed: ${prepared.failures.join(', ')}`);
  let previous = settings.low, savedLateTrial = false;
  for (let index = -2; index < sampleCount; index++) {
    const target = index < 0 ? (index === -2 ? settings.high : settings.low) :
      (index % 2 === 0 ? settings.high - 5 * (Math.floor(index / 2) + 1) : settings.low + 5 * (Math.floor(index / 2) + 1));
    const result = await page.evaluate(args => window.__latency.run(args), { target, previous, index });
    const late = result.videoOnsetMs > targetMs;
    const retainImages = !result.complete || index === -2 || index === 0 || index === sampleCount - 1 || (late && !savedLateTrial);
    const images = retainImages ? await saveImages(result.images, index < 0 ? `warmup-${index + 2}` : `trial-${String(index + 1).padStart(2, '0')}`) : { omitted: 'All numeric evidence retained; images limited to calibration, first/last and first late or incomplete trial.' };
    if (late && index >= 0) savedLateTrial = true;
    delete result.images;
    result.images = images;
    (index >= 0 ? report.trials : report.warmupTrials).push(result);
    console.log(JSON.stringify({ index, target, serviceAckMs: result.serviceAckMs, kitObservedMs: result.kitObservedMs,
      videoOnsetMs: result.videoOnsetMs, videoEndpointMs: result.videoEndpointMs, complete: result.complete }));
    assert.ok(result.complete, `Trial ${index} did not produce both acknowledged state and matching live pixels`);
    assert.equal(result.requestCount, 1, 'One slider event must produce one update');
    assert.ok(result.videoOnsetMs >= result.debounceMs, 'Video changed before the UI sent its update');
    previous = target;
    await page.waitForTimeout(800);
  }
  for (const key of ['debounceMs', 'serviceAckMs', 'serviceRoundTripMs', 'kitObservedMs', 'videoOnsetMs', 'videoEndpointMs']) {
    (report.summary ||= {})[key] = summary(report.trials.map(item => item[key]));
  }
  report.summary.pixelReadbackMs = summary(report.trials.flatMap(item => item.frames.map(frame => frame.readMs)));
  report.summary.observerHttpRoundTripMs = summary(report.trials.flatMap(item => item.polls.map(poll => poll.roundTripMs)));
  report.final = await snapshot();
  assert.deepEqual(report.errors, []);
  assert.ok(report.summary.pixelReadbackMs.p95 <= 20,
    `Pixel observer perturbed the video: readback P95 ${report.summary.pixelReadbackMs.p95} ms`);
  assert.ok(report.summary.videoOnsetMs.p95 <= targetMs,
    `Actual video onset P95 ${report.summary.videoOnsetMs.p95.toFixed(1)} ms exceeds ${targetMs} ms`);
  report.passed = true;
} catch (error) {
  report.failure = String(error.stack || error);
  throw error;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(`${output}/latency-${label}.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, summary: report.summary, failure: report.failure }));
  try { await post('state', original.state); }
  finally { await browser.close(); }
}
