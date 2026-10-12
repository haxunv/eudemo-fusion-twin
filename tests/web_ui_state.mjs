// CPU-only tests of production UI functions; DOM and transport are boundaries.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const declarations = [...source.matchAll(/^(?:async )?function (\w+)\(/gm)];
function productionFunction(name) {
  const index = declarations.findIndex(match => match[1] === name);
  assert.ok(index >= 0, `Production function ${name} exists`);
  return source.slice(declarations[index].index, declarations[index + 1]?.index ?? source.length);
}

class Element {
  constructor(document, dataset = {}) {
    this.document = document;
    this.dataset = dataset;
    this.attributes = new Map();
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
      remove: name => this.classes.delete(name),
      contains: name => this.classes.has(name),
    };
    this.children = [];
    this.parts = new Map();
    this.textContent = '';
    this.innerHTMLWrites = 0;
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name); }
  focus() { this.document.activeElement = this; }
  set disabled(value) {
    this.isDisabled = value;
    if (value && this.document.activeElement === this) this.document.activeElement = null;
  }
  get disabled() { return Boolean(this.isDisabled); }
  set innerHTML(html) {
    this.innerHTMLWrites += 1;
    if (this.children.includes(this.document.activeElement)) this.document.activeElement = null;
    this.children = [...html.matchAll(/data-case-design="([^"]+)" data-case-neon="([^"]+)"/g)].map(match => {
      const button = new Element(this.document, { caseDesign: match[1], caseNeon: match[2] });
      for (const part of ['.case-design', '.case-neon', '.case-value strong', '.case-delta']) {
        button.parts.set(part, new Element(this.document));
      }
      return button;
    });
  }
}

function fixture() {
  const document = { activeElement: null };
  const elements = new Map(['#measure-button', '#measure-dialog', '#comparison-cases', '#comparison-scale'].map(id => [id, new Element(document)]));
  elements.get('#measure-dialog').close = function () { this.open = false; };
  const cameras = ['overview', 'front', 'top', 'section', 'divertor'].map(view => new Element(document, { view }));
  const context = vm.createContext({
    document,
    $: (selector, root) => root ? root.parts.get(selector) : elements.get(selector),
    $$: (selector, root) => selector === '[data-view]' ? cameras : root.children,
    state: { design: 'conventional', equilibrium: 'sof', view: 'overview', mode: 'assembly', visible: {}, selected: '', scenario: 'nominal', power: 2000, heating: 50, flow: 1, inlet: 300, phase: 1, neon: false, heatScale: 'log' },
    result: {}, renderer: {}, manifest: { components: [] },
    revision: -1, serverEpoch: null, committedGeometry: null,
    pendingPatch: {}, inflightPatch: {}, patchPaused: false,
    measureMode: false, lastMeasuredDistance: null, measurementGeneration: 0,
    render() {}, renderComponents() {}, renderDownloads() {}, schedulePatch() {},
    toast() {}, measurementDialogOpens: 0,
    serviceReady: false, language: 'en',
    number(value, decimals = 0) { return value == null ? '—' : Number(value).toFixed(decimals); },
    clearTimeout() {}, setTimeout() { throw new Error('Unexpected background timer'); },
  });
  vm.runInContext('function t(key) { return `${language}:${key}`; }', context);
  vm.runInContext('function openMeasurement() { measurementDialogOpens += 1; }', context);
  for (const name of ['resetMeasurement', 'applySnapshot', 'setState', 'storyCasesReady', 'signedPercent', 'heatRange', 'renderComparison', 'renderCameraSelection', 'startMeasurement', 'selectViewportPoint']) {
    vm.runInContext(productionFunction(name), context, { filename: `app.js:${name}` });
  }
  function snapshot({ revision = 1, design = 'conventional', equilibrium = 'sof', measurement = null, ...patch } = {}) {
    return {
      revision, server_epoch: 'server-1', state: { ...context.state, design, equilibrium, ...patch },
      result: { field_ref: { topology_key: design, equilibrium_key: equilibrium } },
      renderer: { renderer_epoch: 'renderer-1', topology_key: design, equilibrium_key: equilibrium, measurement, selected: '', applied_revision: revision },
    };
  }
  function armMeasurement() {
    context.measureMode = true;
    context.lastMeasuredDistance = 8.5;
    context.renderer.measurement = { type: 'point', points: [[1, 2, 3]] };
    elements.get('#measure-button').classList.toggle('active', true);
  }
  function assertMeasurementCleared() {
    assert.equal(context.measureMode, false);
    assert.equal(context.lastMeasuredDistance, null);
    assert.equal(context.renderer.measurement, null);
    assert.equal(elements.get('#measure-button').classList.contains('active'), false);
  }
  context.applySnapshot(snapshot());
  return { context, document, elements, cameras, snapshot, armMeasurement, assertMeasurementCleared };
}

for (const [key, value] of [['design', 'longleg'], ['equilibrium', 'eof']]) {
  test(`Local ${key} change exits measurement before the server acknowledges it`, () => {
    const f = fixture();
    f.armMeasurement();
    f.context.setState({ [key]: value });
    f.assertMeasurementCleared();
    f.context.inflightPatch = f.context.pendingPatch;
    f.context.pendingPatch = {};
    f.context.applySnapshot(f.snapshot({ revision: 1, measurement: { type: 'point', points: [[1, 2, 3]] } }));
    f.assertMeasurementCleared();
    f.context.inflightPatch = {};
    f.context.applySnapshot(f.snapshot({ revision: 2, [key]: value }));
    f.assertMeasurementCleared();
    assert.equal(f.context.state[key], value);
  });

  test(`Committed ${key} change remains detectable when an optimistic state already matches`, () => {
    const f = fixture();
    f.context.state[key] = value;
    f.armMeasurement();
    f.context.applySnapshot(f.snapshot({ revision: 2, [key]: value, measurement: { type: 'point' } }));
    f.assertMeasurementCleared();
  });
}

test('Same geometry and thermal-only changes preserve an active measurement', () => {
  const f = fixture();
  f.armMeasurement();
  f.context.setState({ design: 'conventional', equilibrium: 'sof', power: 2100 });
  assert.equal(f.context.measureMode, true);
  const measurement = { type: 'point', points: [[1, 2, 3]] };
  f.context.applySnapshot(f.snapshot({ revision: 2, power: 2100, measurement }));
  assert.equal(f.context.measureMode, true);
  assert.equal(f.context.renderer.measurement, measurement);
  assert.equal(f.context.lastMeasuredDistance, 8.5);
});

test('A renderer on the previous geometry cannot restore a stale measurement', () => {
  const f = fixture();
  f.context.applySnapshot(f.snapshot({ revision: 2, design: 'longleg' }));
  f.armMeasurement();
  const pending = f.snapshot({ revision: 2, design: 'longleg', measurement: { type: 'point' } });
  pending.renderer.topology_key = 'conventional';
  f.context.applySnapshot(pending);
  f.assertMeasurementCleared();
});

test('Older snapshots are rejected before changing committed geometry or measurement', () => {
  const f = fixture();
  f.context.applySnapshot(f.snapshot({ revision: 3, design: 'longleg' }));
  f.armMeasurement();
  f.context.applySnapshot(f.snapshot({ revision: 2 }));
  assert.equal(f.context.state.design, 'longleg');
  assert.equal(f.context.committedGeometry.design, 'longleg');
  assert.equal(f.context.measureMode, true);
});

test('Comparison cards retain focus and identity through polling, updates and language changes', () => {
  const f = fixture();
  const { context: c } = f;
  c.result = {
    scenario_label: 'nominal',
    story: {
      comparison_controls: { ...c.state },
      cases: ['conventional', 'longleg'].flatMap(design => [false, true].map(neon => ({ design, neon, peak_divertor_heatflux_MW_m2: neon ? 4 : 8, relative_no_neon_percent: neon ? -50 : 0 }))),
    },
  };
  c.renderComparison();
  const container = f.elements.get('#comparison-cases');
  const buttons = [...container.children];
  assert.equal(buttons.length, 4);
  const focused = buttons[3];
  focused.focus();
  for (let index = 0; index < 5; index++) c.renderComparison();
  c.state.design = 'longleg';
  c.state.neon = true;
  c.language = 'zh';
  c.result.story.cases[3].peak_divertor_heatflux_MW_m2 = 3.25;
  c.renderComparison();
  assert.equal(f.document.activeElement, focused);
  assert.equal(container.innerHTMLWrites, 1);
  container.children.forEach((button, index) => assert.equal(button, buttons[index]));
  assert.equal(focused.getAttribute('aria-pressed'), 'true');
  assert.equal(focused.parts.get('.case-design').textContent, 'zh:longleg');
  assert.equal(focused.parts.get('.case-value strong').textContent, '3.25');
  c.state.heating = 65;
  c.renderComparison();
  assert.equal(focused.parts.get('.case-value strong').textContent, '—');
  assert.equal(focused.getAttribute('aria-busy'), 'true');
  assert.equal(focused.disabled, false);
  assert.equal(f.document.activeElement, focused);
});

test('Each camera change updates visual selection and aria-pressed together', () => {
  const f = fixture();
  for (const view of ['front', 'top', 'section', 'divertor', 'overview']) {
    f.context.state.view = view;
    f.context.renderCameraSelection();
    for (const camera of f.cameras) {
      assert.equal(camera.classList.contains('active'), camera.dataset.view === view);
      assert.equal(camera.getAttribute('aria-pressed'), String(camera.dataset.view === view));
    }
  }
});

test('A delayed measure_start cannot reactivate measurement after a geometry change', async () => {
  const f = fixture();
  let complete;
  f.context.action = type => {
    assert.equal(type, 'measure_start');
    return new Promise(resolve => { complete = resolve; });
  };
  const started = f.context.startMeasurement();
  f.context.setState({ equilibrium: 'eof' });
  complete({ status: 'completed' });
  await started;
  f.assertMeasurementCleared();
});

test('A completed old distance cannot reopen measurement after a newer scene snapshot', async () => {
  const f = fixture();
  f.armMeasurement();
  f.context.action = async type => {
    assert.equal(type, 'measure');
    f.context.applySnapshot(f.snapshot({ revision: 2, design: 'longleg' }));
    return { result: { measurement: { type: 'distance', distance_m: 8.5 } } };
  };
  await f.context.selectViewportPoint(0.5, 0.5);
  f.assertMeasurementCleared();
  assert.equal(f.context.measurementDialogOpens, 0);
});

test('A same-scene measurement completes and subsequent clicks return to picking', async () => {
  const f = fixture();
  const calls = [];
  f.context.action = async type => {
    calls.push(type);
    return { result: { measurement: type === 'measure' ? { type: 'distance', distance_m: 8.5 } : null } };
  };
  await f.context.startMeasurement();
  assert.equal(f.context.measureMode, true);
  await f.context.selectViewportPoint(0.5, 0.5);
  assert.equal(f.context.measureMode, false);
  assert.equal(f.context.renderer.measurement.distance_m, 8.5);
  assert.equal(f.context.measurementDialogOpens, 1);
  await f.context.selectViewportPoint(0.5, 0.5);
  assert.deepEqual(calls, ['measure_start', 'measure', 'pick']);
});
