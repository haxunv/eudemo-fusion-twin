/** Native RTX low/high/low captures; run without another GPU QA session. */
import { mkdir, writeFile } from 'node:fs/promises';
import { base, snapshot, post, complete } from './api.mjs';

const label = process.env.QA_LABEL || 'current';
if (!/^[a-zA-Z0-9_-]+$/.test(label)) throw new Error('Invalid QA label');
const output = new URL(`../../runtime/qa/field-${label}/`, import.meta.url);
await mkdir(output, { recursive: true });
const original = (await snapshot()).state;
const report = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  await post('state', { design: 'conventional', equilibrium: 'reference', scenario: 'nominal',
    mode: 'temperature', view: 'section', power: 1500, flow: 1, inlet: 200,
    phase: 1, cutaway: 80, explode: 0, opacity: 1, visible: { plasma: false },
    selected: '', fieldLines: false, orbit: false, playing: false });
  await complete((await post('action', { type: 'reset_camera', view: 'section' })).request_id);
  for (const [name, inlet] of [['low', 200], ['high', 400], ['return', 200]]) {
    const committed = await post('state', { inlet });
    const deadline = Date.now() + 20000;
    while ((await snapshot()).renderer.applied_field_key !== committed.field_ref.key) {
      if (Date.now() > deadline) throw new Error('Field application timeout');
      await delay(50);
    }
    await delay(5000);
    const capture = await complete((await post('action', { type: 'capture' })).request_id);
    const response = await fetch(new URL(capture.result.capture_url, base));
    if (!response.ok) throw new Error(`Capture download: ${response.status}`);
    await writeFile(new URL(`${name}.png`, output), Buffer.from(await response.arrayBuffer()));
    const state = await snapshot();
    report.push({ name, inlet, field: state.field_ref, renderer: state.renderer });
    await writeFile(new URL('report.json', output), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ name, reset: state.renderer.render_reset,
      pending: state.renderer.dlss_reset_pending, responsive: state.renderer.responsive_denoising }));
  }
} finally { await post('state', original); }
