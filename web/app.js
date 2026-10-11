const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const translations = {
  zh: {
    digitalTwin: '聚变数字孪生', connecting: '正在连接', connected: 'RTX 实时串流', preview: 'RTX 预览', offline: '渲染器未连接', serverOffline: '服务未连接', fullscreen: '全屏',
    views: '视角', orbit: '环绕', assembly: '装配', assemblyTree: '模型装配树', measure: '测量', measureTitle: '部件尺寸与双点测量', reset: '重置', resetView: '恢复默认视角',
    searchComponents: '搜索部件', isolate: '隔离所选', showAll: '全部显示', selectComponent: '选择部件查看工程属性', explore: '探索', compare: '对比', settings: '工况设置', scenario: '运行工况',
    nominal: '额定运行', ramp: '热负荷爬升', lowflow: '低冷却流量', highload: '高热负荷', fusionPower: '假定热负荷', coolantFlow: '冷却流量', inletTemperature: '冷却剂入口温度',
    visualization: '可视化方式', assemblyMode: '工程装配', temperature: '温度', heatflux: '热流密度', magnetic: '磁力线', slice: '截面场', adjustment: '可视化调整', cutaway: '剖开角度', explode: '装配爆炸', opacity: '不透明度', fieldLines: '叠加磁力线',
    compareTitle: '工况对比', compareDescription: '比较参考工况与当前工况的热管理响应。', baseline: '参考工况', candidate: '当前工况', compareNote: '同一几何模型 · 同一数据生成方法', trendTitle: '时间历程', surfaceTemperature: '峰值表面温度',
    readouts: '计算结果', peakTemperature: '峰值温度', peakHeatflux: '峰值热流', outletTemperature: '出口温度', coolingMargin: '温度裕量', fieldCompute: '场计算', export: '导出工况', screenshot: '截图',
    play: '播放 / 暂停', discharge: '热响应过程', rampUp: '起始', flatTop: '升温', rampDown: '稳态', dataProvenance: '数据来源与模型说明', initializing: '正在准备工程场景', initializingDetail: '加载 EU-DEMO 装配与 RTX 渲染器',
    dimensions: '工程尺寸', cadProvenance: '公开概念设计生成的反应堆装配。保留部件层级、材料和源模型信息。', engineeringDemo: '工程演示数据', fieldProvenance: '预制或简化模型生成的场数据用于交互展示；工况、单位和计算参数随导出文件提供。', renderProvenance: 'OpenUSD 场景通过本机 Kit 渲染，WebRTC 传输交互画面。',
    overview: '全堆总览', front: '正视图', top: '俯视图', section: '剖面视图', divertor: '偏滤器', overviewTitle: 'EU-DEMO 反应堆装配', frontTitle: '环向装配 · 正视', topTitle: '磁体与包层 · 俯视', sectionTitle: '堆内结构 · 剖面', divertorTitle: '偏滤器 · 热管理',
    overviewDescription: '公开 CAD 装配 · 交互工况与多物理场', frontDescription: 'TF / PF 线圈、真空室与等离子体边界', topDescription: '环向扇区、径向层级与维护通道', sectionDescription: '包层、屏蔽结构与真空边界', divertorDescription: '等离子体面对部件与热流分布',
    material: '材料', parts: '零部件', triangles: '三角面', source: '来源', dimensionsXYZ: '包围盒 X × Y × Z', downloadStep: '下载 STEP 源模型', downloadUsd: '下载 USD 场景', sourceCad: '源 CAD 文件', noResult: '等待计算结果', noHistory: '计算后显示时间历程',
    selectFirst: '请先在装配树中选择部件', dimensionsHint: '所选部件的轴对齐包围盒尺寸，单位为米。', measureHint: '在三维视口中依次点击两个表面点。', startMeasure: '双点测量', clearMeasure: '清除测量', measurementStarted: '测量已开启，请在模型表面选择两个点', measuredDistance: '两点距离', noBounds: '当前部件尚无尺寸数据',
    exportDone: '已导出当前工况、计算结果与来源说明', screenshotDone: '已保存 RTX 渲染截图', screenshotUnavailable: '等待 RTX 画面后可保存截图', requestFailed: '操作未完成，请检查本地服务', updated: '工况已更新', noComponents: '没有匹配的部件', dataPending: '等待数据源信息', reference: '参考', gpuCompute: 'GPU 场计算', cpuCompute: 'CPU 场计算', liveRender: '实时渲染', connectHint: '点击重新连接串流', sourceEquilibrium: '公开平衡数据', heatfluxLimit: '色标上限 12 MW/m²', temperatureLimit: '色标上限 1,100 °C',
    compareAssembly: '查看当前工况', renderPending: 'RTX 正在加载场景', rendererError: '渲染器启动失败，检查运行日志', dimensionX: '宽度 X', dimensionY: '深度 Y', dimensionZ: '高度 Z', demoTimeline: '600 s · 演示时间',
  },
  en: {
    digitalTwin: 'Fusion Digital Twin', connecting: 'Connecting', connected: 'RTX LIVE STREAM', preview: 'RTX PREVIEW', offline: 'Renderer offline', serverOffline: 'Service offline', fullscreen: 'Fullscreen',
    views: 'VIEWS', orbit: 'ORBIT', assembly: 'Assembly', assemblyTree: 'ASSEMBLY TREE', measure: 'Measure', measureTitle: 'Component dimensions and point measurement', reset: 'Reset', resetView: 'Reset view',
    searchComponents: 'Search components', isolate: 'Isolate', showAll: 'Show all', selectComponent: 'Select a component to inspect its properties', explore: 'Explore', compare: 'Compare', settings: 'SETTINGS', scenario: 'Scenario',
    nominal: 'Nominal operation', ramp: 'Thermal load ramp', lowflow: 'Reduced coolant flow', highload: 'High heat load', fusionPower: 'Assumed thermal load', coolantFlow: 'Coolant flow', inletTemperature: 'Coolant inlet temperature',
    visualization: 'VISUALIZATION TECHNIQUES', assemblyMode: 'Assembly', temperature: 'Temperature', heatflux: 'Heat flux', magnetic: 'Field lines', slice: 'Field section', adjustment: 'VISUALIZATION ADJUSTMENT', cutaway: 'Cutaway angle', explode: 'Explode', opacity: 'Opacity', fieldLines: 'Show magnetic field lines',
    compareTitle: 'SCENARIO COMPARISON', compareDescription: 'Thermal response of the reference and active operating scenarios.', baseline: 'BASELINE', candidate: 'CURRENT', compareNote: 'Same geometry · Same field-generation method', trendTitle: 'TIME HISTORY', surfaceTemperature: 'Peak surface temperature',
    readouts: 'SIMULATION READOUTS', peakTemperature: 'Peak temperature', peakHeatflux: 'Peak heat flux', outletTemperature: 'Outlet temperature', coolingMargin: 'Thermal margin', fieldCompute: 'Field calculation', export: 'Export scenario', screenshot: 'Capture',
    play: 'Play / pause', discharge: 'THERMAL RESPONSE', rampUp: 'Start', flatTop: 'Warm-up', rampDown: 'Steady', dataProvenance: 'DATA & MODEL PROVENANCE', initializing: 'Preparing the engineering scene', initializingDetail: 'Loading EU-DEMO assembly and RTX renderer',
    dimensions: 'ENGINEERING DIMENSIONS', cadProvenance: 'Reactor assembly generated from an open concept design. Component hierarchy, materials and source references are retained.', engineeringDemo: 'Engineering demonstration data', fieldProvenance: 'Precomputed or reduced-model fields support the interactive demonstration. Scenarios, units and calculation inputs are included in exports.', renderProvenance: 'The OpenUSD scene is rendered locally by Kit and streamed interactively through WebRTC.',
    overview: 'Overview', front: 'Front', top: 'Top', section: 'Section', divertor: 'Divertor', overviewTitle: 'EU-DEMO reactor assembly', frontTitle: 'Toroidal assembly · Front', topTitle: 'Magnets & blanket · Top', sectionTitle: 'Internal structure · Section', divertorTitle: 'Divertor · Thermal response',
    overviewDescription: 'Public CAD assembly · Interactive scenarios & multiphysics fields', frontDescription: 'TF / PF coils, vacuum vessel and plasma boundary', topDescription: 'Toroidal sectors, radial layers and maintenance access', sectionDescription: 'Blanket, shielding and vacuum boundary', divertorDescription: 'Plasma-facing components and heat-flux distribution',
    material: 'Material', parts: 'Parts', triangles: 'Triangles', source: 'Source', dimensionsXYZ: 'Bounding box X × Y × Z', downloadStep: 'Download source STEP', downloadUsd: 'Download USD scene', sourceCad: 'Source CAD files', noResult: 'Waiting for calculation', noHistory: 'History appears after calculation',
    selectFirst: 'Select a component in the assembly tree first', dimensionsHint: 'Axis-aligned bounding-box dimensions of the selected component, in metres.', measureHint: 'Select two surface points in the 3D viewport.', startMeasure: 'Point-to-point', clearMeasure: 'Clear measurement', measurementStarted: 'Measurement enabled. Select two points on the model.', measuredDistance: 'Point-to-point distance', noBounds: 'Dimensions are not available for this component',
    exportDone: 'Scenario, results and provenance exported', screenshotDone: 'RTX render saved', screenshotUnavailable: 'Capture is available after the RTX image arrives', requestFailed: 'Action failed. Check the local service.', updated: 'Scenario updated', noComponents: 'No matching components', dataPending: 'Waiting for source metadata', reference: 'Reference', gpuCompute: 'GPU field calculation', cpuCompute: 'CPU field calculation', liveRender: 'Live rendering', connectHint: 'Click to reconnect the stream', sourceEquilibrium: 'Public equilibrium data', heatfluxLimit: 'Color scale capped at 12 MW/m²', temperatureLimit: 'Color scale capped at 1,100 °C',
    compareAssembly: 'View current scenario', renderPending: 'RTX is loading the scene', rendererError: 'Renderer failed to start. Check runtime logs.', dimensionX: 'Width X', dimensionY: 'Depth Y', dimensionZ: 'Height Z', demoTimeline: '600 s · DEMO TIME',
  },
};

let language = localStorage.getItem('fusion-language') === 'en' ? 'en' : 'zh';
let manifest = { components: [] };
let state = { view: 'overview', tab: 'explore', mode: 'assembly', scenario: 'nominal', power: 2000, flow: 1, inlet: 300, phase: 0.65, cutaway: 80, explode: 0, opacity: 1, visible: {}, selected: '', fieldLines: false, orbit: false, playing: false };
let result = {};
let renderer = {};
let revision = -1;
let streamLive = false;
let previewReady = false;
let serviceReady = false;
let pendingPatch = {};
let patchTimer;
let sendingPatch = false;
let previewLoading = false;
let lastPreview = 0;
let streamerStarted = false;
let toastTimer;
let measureMode = false;
let pointerStart = null;
let lastMeasuredDistance = null;
let measureCommandSeq = 0;

const t = (key) => translations[language][key] || key;
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const number = (value, decimals = 0) => Number.isFinite(Number(value)) && value !== null && value !== '' ? Number(value).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { maximumFractionDigits: decimals, minimumFractionDigits: decimals }) : '—';
const componentName = (component) => component?.[`name_${language}`] || component?.name_en || component?.name || component?.id || '—';
const selectedComponent = () => manifest.components?.find((component) => component.id === state.selected);

function applyLanguage() {
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.title = language === 'zh' ? 'EU-DEMO · 聚变数字孪生' : 'EU-DEMO · Fusion Digital Twin';
  $$('[data-i18n]').forEach((element) => { element.textContent = t(element.dataset.i18n); });
  $$('[data-title]').forEach((element) => { element.title = t(element.dataset.title); element.setAttribute('aria-label', t(element.dataset.title)); });
  $$('[data-placeholder]').forEach((element) => { element.placeholder = t(element.dataset.placeholder); });
  $$('[data-lang]').forEach((button) => button.classList.toggle('active', button.dataset.lang === language));
  renderCameras();
  renderComponents();
  renderDownloads();
  render();
  if ($('#measure-dialog').open) renderMeasurement();
}

const cameraDrawings = {
  overview: '<g transform="translate(50 26) rotate(-22)"><ellipse rx="25" ry="16"/><ellipse rx="17" ry="10"/><ellipse rx="10" ry="6"/><path d="M-25 0v9a25 16 0 0 0 50 0V0M-17 0v8a17 10 0 0 0 34 0V0M0-16v5m-16-7 4 7m28-7-4 7m12 9-7-1M-25 0h8"/><path d="M0-16v-6m-25 24-6 5m56-5 6 5"/></g>',
  front: '<g transform="translate(50 28)"><path d="M-26 15v-24q0-13 13-13h26q13 0 13 13v24M-19 15V-7q0-11 10-11H9q10 0 10 11v22M-12 15V-5q0-10 7-10H5q7 0 7 10v20M-5 15v-26M5 15v-26M-29 15h58M-24 19h48"/><path d="M-30-10h60m-59 22h58"/></g>',
  top: '<g transform="translate(50 28)"><circle r="23"/><circle r="17"/><circle r="11"/><circle r="5"/><path d="M0-23v12M0 11v12M-23 0h12m22 0h12M-16-16l8 8m16 16 8 8M16-16 8-8m-16 16-8 8M-9-21l5 11m8 20 5 11M21-9 10-4m-20 8-11 5M-21-9l11 5m20 8 11 5M9-21 4-10m-8 20-5 11"/></g>',
  section: '<g transform="translate(50 28)"><path d="M-25 15v-25q0-12 11-12h9v40m10 0v-40h9q11 0 11 12v25M-20 15V-8q0-10 10-10v31m20 0v-31q10 0 10 10v23M-16 8q-4-12 4-20m24 0q8 8 4 20M-19 15l8-7 6 10m10 0 6-10 8 7M-30 19h60"/><path d="M-1-22v43" stroke-dasharray="2 3"/></g>',
  divertor: '<g transform="translate(50 25)"><path d="M-30-11q-1 18 17 25l8-11h10l8 11q18-7 17-25M-30-6q1 11 15 16l6-10m18 0 6 10q14-5 15-16M-22 12v7h44v-7M-12 14v5m24-5v5M0-16v17"/><path d="m-5-5 5 6 5-6M-5-17q-11 9-13 16m23-16q11 9 13 16" stroke="#86ab66"/></g>',
};

function renderCameras() {
  $('#camera-buttons').innerHTML = Object.entries(cameraDrawings).map(([view, drawing], index) => `<button class="camera-button ${state.view === view ? 'active' : ''}" data-view="${view}" title="${t(view)}" aria-label="${t(view)}"><span class="view-number">0${index + 1}</span><svg viewBox="0 0 100 56" aria-hidden="true">${drawing}</svg><span class="view-label">${t(view)}</span></button>`).join('');
}

function getDimensions(component) {
  const bounds = component?.bounds_m;
  if (!bounds) return null;
  if (bounds.min && bounds.max) return bounds.max.map((value, index) => Math.abs(value - bounds.min[index]));
  if (Array.isArray(bounds) && bounds.length === 2 && Array.isArray(bounds[0])) return bounds[1].map((value, index) => Math.abs(value - bounds[0][index]));
  if (Array.isArray(bounds) && bounds.length === 6) return bounds.slice(3).map((value, index) => Math.abs(value - bounds[index]));
  if (bounds.size) return bounds.size;
  return null;
}

function renderComponents() {
  const query = $('#component-search').value.trim().toLowerCase();
  const components = manifest.components || [];
  const visible = components.filter((component) => [component.name_en, component.name_zh, component.id].some((value) => String(value || '').toLowerCase().includes(query)));
  const partCount = components.reduce((sum, component) => sum + (component.part_count || 0), 0);
  $('#assembly-count').textContent = `${number(components.length)} ${language === 'zh' ? '系统' : 'systems'} / ${number(partCount)} ${t('parts')}`;
  $('#component-tree').innerHTML = visible.length ? visible.map((component) => `<div class="component-row ${state.selected === component.id ? 'selected' : ''}" data-component="${esc(component.id)}" role="button" tabindex="0" aria-pressed="${state.selected === component.id}"><input type="checkbox" data-visible="${esc(component.id)}" ${state.visible?.[component.id] !== false ? 'checked' : ''} aria-label="${t('showAll')} ${esc(componentName(component))}"><svg viewBox="0 0 20 20"><path d="m10 2 7 4v8l-7 4-7-4V6zm-7 4 7 4 7-4m-7 4v8"/></svg><span>${esc(componentName(component))}</span><small>${number(component.part_count)}</small></div>`).join('') : `<p class="empty-chart">${t('noComponents')}</p>`;
  renderProperties();
}

function renderProperties() {
  const component = selectedComponent();
  const properties = $('#component-properties');
  if (!component) { properties.innerHTML = `<p>${t('selectComponent')}</p>`; return; }
  const dimensions = getDimensions(component);
  const rows = [[t('material'), component.material], [t('parts'), number(component.part_count)], [t('triangles'), number(component.triangle_count)], [t('source'), typeof component.source === 'string' ? component.source : 'bluemira / EU-DEMO']];
  if (dimensions) rows.push([t('dimensionsXYZ'), dimensions.map((value) => number(value, 2)).join(' × ') + ' m']);
  properties.innerHTML = `<h3>${esc(componentName(component))}</h3>${rows.map(([key, value]) => `<div class="property-row"><span>${esc(key)}</span><span>${esc(value || '—')}</span></div>`).join('')}<button class="outline-button" id="component-measure">${t('dimensions')}</button>${component.source_step ? `<a class="outline-button" href="/assets/${esc(component.source_step)}" download>${t('downloadStep')}</a>` : ''}`;
}

function renderDownloads() {
  const downloads = manifest.downloads || {};
  const links = [];
  if (downloads.step) links.push([t('downloadStep'), downloads.step]);
  if (downloads.usd) links.push([t('downloadUsd'), downloads.usd]);
  if (manifest.step_url) links.push([t('downloadStep'), manifest.step_url]);
  if (manifest.usd_url) links.push([t('downloadUsd'), manifest.usd_url]);
  if (manifest.stage) links.push([t('downloadUsd'), '/api/download/usd.zip']);
  if ((manifest.components || []).some((component) => component.source_step)) links.push([t('sourceCad'), '/api/download/cad.zip']);
  $('#source-downloads').innerHTML = links.length ? `<div class="source-downloads">${links.map(([label, url]) => `<a class="outline-button" href="${esc(url)}" download>${esc(label)}</a>`).join('')}</div>` : '';
}

function sliderValue(key) {
  if (key === 'power') return `${number(state.power)} <small>MW</small>`;
  if (key === 'flow') return `${number(state.flow * 100)} <small>%</small>`;
  if (key === 'inlet') return `${number(state.inlet)} <small>°C</small>`;
  if (key === 'cutaway') return `${number(state.cutaway)}°`;
  return `${number(state[key] * 100)}%`;
}

function renderConnection() {
  const connection = $('#connection');
  const label = streamLive ? 'connected' : previewReady ? 'preview' : serviceReady ? 'connecting' : 'serverOffline';
  connection.classList.toggle('online', streamLive);
  connection.classList.toggle('error', !serviceReady);
  $('span', connection).textContent = t(label);
  connection.title = t('connectHint');
  $('#viewport').classList.toggle('live', streamLive);
  $('#loading-state').hidden = streamLive || previewReady;
  const rendererStatus = String(renderer.status || '').toLowerCase();
  $('#loading-detail').textContent = renderer.error || rendererStatus.includes('error') ? t('rendererError') : t(serviceReady ? 'renderPending' : 'initializingDetail');
  const gpu = result.gpu_name || renderer.gpu_name || renderer.gpu || renderer.device || result.device || result.gpu_device;
  $('#gpu-label').textContent = typeof gpu === 'string' ? gpu : 'GPU —';
}

function renderLegend() {
  const modes = { temperature: ['temperature', '°C', 300, 1100], heatflux: ['heatflux', 'MW/m²', 0, 12], slice: ['temperature', 'keV', 0, 30], magnetic: ['magnetic', t('sourceEquilibrium'), null, null] };
  const legend = modes[state.mode];
  $('#field-legend').hidden = !legend;
  if (!legend) return;
  $('#legend-title').textContent = t(legend[0]);
  $('#legend-unit').textContent = legend[1];
  $('.colormap').hidden = state.mode === 'magnetic';
  $('#legend-min').textContent = legend[2] === null ? '' : number(legend[2]);
  const overflow = state.mode === 'heatflux' ? result.peak_heatflux_MW_m2 > 12 : state.mode === 'slice' ? false : result.peak_temperature_C > 1100;
  $('#legend-max').textContent = legend[3] === null ? '' : number(legend[3]) + (overflow ? '+' : '');
}

function renderResults() {
  const outputs = { 'kpi-temperature': ['peak_temperature_C', 0], 'kpi-heatflux': ['peak_heatflux_MW_m2', 2], 'kpi-outlet': ['outlet_temperature_C', 0], 'kpi-margin': ['cooling_margin_C', 0] };
  for (const [id, [key, decimals]] of Object.entries(outputs)) $(`#${id}`).textContent = number(result[key], decimals);
  $('#kpi-margin').style.color = result.cooling_margin_C < 0 ? '#e2a08c' : '';
  const backend = result.compute_backend || result.backend || result.engine || '';
  $('#compute-badge').textContent = backend || (result.gpu_ms != null ? 'CUDA / Warp' : '—');
  $('#gpu-time').textContent = result.gpu_ms != null ? `${number(result.gpu_ms, 2)} ms` : result.cpu_ms != null ? `${number(result.cpu_ms, 2)} ms · CPU` : '—';
  const sourceLabel = result.source_label === 'synthetic_thermal_bluemira_equilibrium' ? (language === 'zh' ? '合成热边界条件与简化传热模型 / Bluemira 公开磁平衡数据' : 'Synthetic thermal boundaries and reduced heat-transfer model / Bluemira magnetic equilibrium') : result.source_label || manifest.source_label || t('dataPending');
  const assumptions = result.assumptions || {};
  const assumptionLabels = { thermal: ['传热模型', 'Thermal model'], coolant: ['冷却剂', 'Coolant'], limit: ['演示阈值', 'Demonstration threshold'], magnetics: ['磁平衡', 'Magnetic equilibrium'], plasma_slice: ['等离子体截面', 'Plasma section'] };
  const assumptionChinese = {
    'Synthetic surface heat-flux distribution and wall thermal resistance; not normalized as a conservative full-reactor heat solution': '合成表面热流分布与壁面热阻模型；未按全堆功率守恒进行归一化。',
    'Separate assumed helium circuit energy balance: cp=5200 J/(kg K), nominal flow=3500 kg/s': '采用独立假定的氦冷却回路能量平衡：比热 5,200 J/(kg·K)，额定质量流量 3,500 kg/s。',
    '900 degC demonstration threshold; not a material qualification limit': '900 °C 为演示温度阈值，未用于材料合格评定。',
    'Bluemira reference equilibrium, Bphi=fvac/R approximation; unchanged by thermal controls': '使用 Bluemira 参考平衡与 Bφ = fvac/R 近似；热负荷和冷却参数不改变磁平衡。',
    'Synthetic 25 keV core profile shaped by source normalized poloidal flux': '依据源数据归一化极向磁通构造合成的 25 keV 核心温度剖面。',
  };
  const sourceMarkup = `${esc(sourceLabel)}${Object.keys(assumptions).length ? `<details class="assumptions"><summary>${language === 'zh' ? '计算假设与适用范围' : 'Calculation assumptions & scope'}</summary>${Object.entries(assumptions).map(([key, value]) => `<p><strong>${esc(assumptionLabels[key]?.[language === 'zh' ? 0 : 1] || key)}</strong><br>${esc(language === 'zh' ? assumptionChinese[value] || value : value)}</p>`).join('')}</details>` : ''}`;
  if ($('#source-description').dataset.content !== sourceMarkup) { $('#source-description').innerHTML = sourceMarkup; $('#source-description').dataset.content = sourceMarkup; }
}

function renderComparison() {
  $('#compare-candidate').textContent = t(state.scenario);
  const compare = result.comparison;
  const metrics = [['peak_temperature_C', 'peakTemperature', '°C', 0], ['peak_heatflux_MW_m2', 'peakHeatflux', 'MW/m²', 2], ['outlet_temperature_C', 'outletTemperature', '°C', 0], ['cooling_margin_C', 'coolingMargin', '°C', 0]];
  $('#comparison-results').innerHTML = metrics.map(([key, label, unit, precision]) => {
    const baseline = compare?.baseline?.[key];
    const candidate = compare?.candidate?.[key];
    const delta = compare?.delta?.[key] ?? (baseline != null && candidate != null ? candidate - baseline : null);
    const signed = delta == null ? '—' : `${delta > 0 ? '+' : ''}${number(delta, precision)} ${unit}`;
    const ratio = candidate != null && baseline != null ? Math.max(0, Math.min(100, candidate / Math.max(Math.abs(candidate), Math.abs(baseline), 1) * 100)) : 0;
    const worse = key === 'cooling_margin_C' ? delta < 0 : delta > 0;
    return `<div class="compare-metric"><header><span>${t(label)}</span><small class="${worse ? 'negative' : ''}">${signed}</small></header><div class="compare-values"><span>${number(baseline, precision)}</span><span>${number(candidate, precision)}</span></div><div class="compare-bars"><i style="width:${ratio}%"></i></div></div>`;
  }).join('');
  renderHistory();
}

function renderHistory() {
  const history = result.history;
  const chart = $('#history-chart');
  const entries = Array.isArray(history) ? history.map((item, index) => ({ x: Number(item.phase ?? item.time ?? index), y: Number(item.peak_temperature_C ?? item.temperature_C ?? item.temperature) })).filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y)) : [];
  if (entries.length < 2) { chart.innerHTML = `<span class="empty-chart">${t('noHistory')}</span>`; return; }
  const xs = entries.map((item) => item.x), ys = entries.map((item) => item.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const points = entries.map((item) => `${8 + (item.x - minX) / (maxX - minX || 1) * 272},${95 - (item.y - minY) / (maxY - minY || 1) * 74}`).join(' ');
  chart.innerHTML = `<svg viewBox="0 0 290 115" role="img" aria-label="${t('surfaceTemperature')}"><path d="M8 20h272M8 58h272M8 96h272" stroke="#ffffff14" stroke-width=".7"/><polyline points="${points}" fill="none" stroke="#8db96d"/><text x="8" y="111" fill="#728569" stroke="none" font-size="8">${number(minX, 1)}</text><text x="280" y="111" fill="#728569" stroke="none" font-size="8" text-anchor="end">${number(maxX, 1)}</text><text x="280" y="13" fill="#9ab48b" stroke="none" font-size="8" text-anchor="end">${number(maxY)} °C</text></svg>`;
}

function render() {
  $$('[data-tab]').forEach((button) => { button.classList.toggle('active', button.dataset.tab === state.tab); button.setAttribute('aria-selected', button.dataset.tab === state.tab); });
  $('#explore-panel').hidden = state.tab === 'compare';
  $('#compare-panel').hidden = state.tab !== 'compare';
  $$('[data-mode]').forEach((button) => { button.classList.toggle('active', button.dataset.mode === state.mode); button.setAttribute('aria-pressed', button.dataset.mode === state.mode); });
  $$('[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === state.view));
  $$('[data-state]').forEach((input) => {
    const key = input.dataset.state;
    if (document.activeElement !== input) input.value = state[key];
    input.style.setProperty('--progress', `${(Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min)) * 100}%`);
    const output = $(`#${key}-value`);
    if (output) output.innerHTML = sliderValue(key);
  });
  $('#scenario-select').value = state.scenario;
  $('#fieldlines-toggle').checked = state.fieldLines;
  $('#orbit-button').classList.toggle('active', state.orbit);
  $('#play-button').classList.toggle('playing', state.playing);
  $('#play-button').setAttribute('aria-pressed', state.playing);
  $('#view-title').textContent = t(`${state.view}Title`);
  $('#view-subtitle').textContent = t(`${state.view}Description`);
  renderLegend();
  renderConnection();
  renderResults();
  renderComparison();
  if ($('#measure-dialog').open) renderMeasurement();
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

function applySnapshot(snapshot) {
  if (snapshot.revision != null && snapshot.revision < revision) return;
  revision = snapshot.revision ?? revision;
  const previousSelected = state.selected;
  const previousVisibility = JSON.stringify(state.visible);
  state = { ...state, ...(snapshot.state || {}), ...pendingPatch };
  result = snapshot.result || result;
  renderer = snapshot.renderer || renderer;
  if (renderer.selected && renderer.applied_revision >= revision && state.selected !== renderer.selected) {
    state.selected = renderer.selected;
    pendingPatch.selected = renderer.selected;
    clearTimeout(patchTimer);
    patchTimer = setTimeout(flushPatch, 0);
  }
  serviceReady = true;
  if (previousSelected !== state.selected || previousVisibility !== JSON.stringify(state.visible)) renderComponents();
  render();
  const distance = renderer.measurement?.type === 'distance' ? renderer.measurement.distance_m : null;
  if (measureMode && renderer.command_seq >= measureCommandSeq && distance != null && distance !== lastMeasuredDistance) { lastMeasuredDistance = distance; measureMode = false; $('#measure-button').classList.remove('active'); openMeasurement(); }
}

function setState(patch, delay = 0) {
  pendingPatch = { ...pendingPatch, ...patch };
  state = { ...state, ...patch };
  render();
  if ('selected' in patch || 'visible' in patch) renderComponents();
  clearTimeout(patchTimer);
  patchTimer = setTimeout(flushPatch, delay);
}

async function flushPatch() {
  if (sendingPatch || !Object.keys(pendingPatch).length) return;
  const patch = pendingPatch;
  pendingPatch = {};
  sendingPatch = true;
  try { applySnapshot(await api('/api/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) })); }
  catch { serviceReady = false; toast(t('requestFailed')); renderConnection(); }
  finally { sendingPatch = false; if (Object.keys(pendingPatch).length) flushPatch(); }
}

async function action(type, extra = {}) {
  try { return await api('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type, ...extra }) }); }
  catch { toast(t('requestFailed')); return null; }
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.hidden = true; }, 3500);
}

function toggleAssembly(open = $('#assembly-drawer').hidden) {
  $('#assembly-drawer').hidden = !open;
  $('#assembly-button').classList.toggle('active', open);
  $('#assembly-button').setAttribute('aria-expanded', open);
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderMeasurement() {
  const component = selectedComponent();
  const dimensions = renderer.measurement?.type === 'bounds' && renderer.measurement.component === component?.id ? renderer.measurement.dimensions_m : getDimensions(component);
  const measurement = renderer.measurement;
  const distance = measurement?.distance_m ?? measurement?.distance;
  $('#measurement-content').innerHTML = `<h3>${esc(component ? componentName(component) : t('dimensions'))}</h3>${dimensions ? `<p>${t('dimensionsHint')}</p><div class="dimension-cards">${dimensions.map((value, index) => `<div><span>${t(['dimensionX', 'dimensionY', 'dimensionZ'][index])}</span><strong>${number(value, 2)}</strong> <small>m</small></div>`).join('')}</div>` : `<p>${t(component ? 'noBounds' : 'selectComponent')}</p>`}${distance != null ? `<p>${t('measuredDistance')}</p><div class="measure-result">${number(distance, 3)} <small>m</small></div>` : ''}<p>${t('measureHint')}</p><div class="measurement-actions"><button class="outline-button" id="start-measure-button">${t('startMeasure')}</button><button class="outline-button" id="clear-measure-button">${t('clearMeasure')}</button></div>`;
}

function openMeasurement() {
  renderMeasurement();
  $('#measure-dialog').showModal();
}

function startStream() {
  if (!window.FusionStreamer || streamerStarted) return;
  streamerStarted = true;
  window.FusionStreamer.connect({
    onConnected: () => { streamLive = true; renderConnection(); },
    onDisconnected: () => { streamLive = false; streamerStarted = false; renderConnection(); },
    onError: () => { streamLive = false; streamerStarted = false; renderConnection(); },
  });
}

function updatePreview() {
  if (streamLive || previewLoading || Date.now() - lastPreview < 2000) return;
  previewLoading = true;
  lastPreview = Date.now();
  const image = new Image();
  const url = `/api/preview.png?t=${lastPreview}`;
  image.onload = () => {
    $('#render-preview').src = url;
    $('#render-preview').hidden = false;
    previewReady = true;
    previewLoading = false;
    renderConnection();
  };
  image.onerror = () => { previewLoading = false; };
  image.src = url;
}

async function poll() {
  try {
    if (!sendingPatch && !Object.keys(pendingPatch).length) applySnapshot(await api('/api/state'));
    updatePreview();
    if (!streamerStarted && serviceReady && renderer.ready) startStream();
  } catch { serviceReady = false; renderConnection(); }
  setTimeout(poll, document.hidden ? 2500 : 1000);
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  const componentRow = event.target.closest('[data-component]');
  if (componentRow && !event.target.matches('input')) setState({ selected: componentRow.dataset.component });
  if (!button) return;
  if (button.dataset.lang) { language = button.dataset.lang; localStorage.setItem('fusion-language', language); applyLanguage(); }
  if (button.dataset.view) setState({ view: button.dataset.view, orbit: false });
  if (button.dataset.mode) {
    const mode = button.dataset.mode;
    const plasma = manifest.components.find((component) => component.id === 'plasma');
    setState({ mode, selected: '', visible: { ...state.visible, plasma: mode === 'assembly' ? plasma?.default_visible !== false : false } });
  }
  if (button.dataset.tab) setState({ tab: button.dataset.tab });
  if (button.dataset.close === 'assembly-drawer') toggleAssembly(false);
  if (button.hasAttribute('data-dialog-close')) button.closest('dialog').close();
  switch (button.id) {
    case 'assembly-button': toggleAssembly(); break;
    case 'orbit-button': setState({ orbit: !state.orbit }); break;
    case 'play-button': setState({ playing: !state.playing }); break;
    case 'reset-view-button': setState({ view: 'overview', selected: '', cutaway: 80, explode: 0, opacity: 1, orbit: false, visible: Object.fromEntries((manifest.components || []).map((component) => [component.id, component.id === 'plasma' && state.mode !== 'assembly' ? false : component.default_visible !== false])) }); await action('reset_camera', { view: 'overview' }); break;
    case 'isolate-button':
      if (!state.selected) { toast(t('selectFirst')); break; }
      setState({ visible: Object.fromEntries(manifest.components.map((component) => [component.id, component.id === state.selected])) }); break;
    case 'show-all-button': setState({ visible: Object.fromEntries(manifest.components.map((component) => [component.id, true])) }); break;
    case 'measure-button': case 'component-measure': openMeasurement(); break;
    case 'start-measure-button': {
      const response = await action('measure_start');
      if (response) { measureMode = true; measureCommandSeq = response.command_seq; lastMeasuredDistance = null; $('#measure-dialog').close(); $('#measure-button').classList.add('active'); toast(t('measurementStarted')); } break;
    }
    case 'clear-measure-button':
      if (await action('measure_clear')) { measureMode = false; lastMeasuredDistance = null; renderer.measurement = null; $('#measure-button').classList.remove('active'); renderMeasurement(); } break;
    case 'provenance-button': $('#provenance-dialog').showModal(); break;
    case 'fullscreen-button': if (!document.fullscreenElement) document.documentElement.requestFullscreen?.(); else document.exitFullscreen?.(); break;
    case 'export-button':
      try {
        const exported = await api('/api/export');
        download(new Blob([JSON.stringify(exported, null, 2)], { type: 'application/json' }), `eudemo-${exported.state?.scenario || state.scenario}-${new Date().toISOString().slice(0, 19).replaceAll(':', '-')}.json`);
        toast(t('exportDone'));
      } catch { toast(t('requestFailed')); } break;
    case 'screenshot-button':
      try {
        if (streamLive && $('#remote-video').videoWidth) {
          const canvas = document.createElement('canvas');
          canvas.width = $('#remote-video').videoWidth;
          canvas.height = $('#remote-video').videoHeight;
          canvas.getContext('2d').drawImage($('#remote-video'), 0, 0);
          canvas.toBlob((blob) => { if (blob) { download(blob, `eudemo-${state.view}.png`); toast(t('screenshotDone')); } });
        } else {
          const response = await fetch(`/api/preview.png?t=${Date.now()}`);
          if (!response.ok) throw new Error('preview unavailable');
          download(await response.blob(), `eudemo-${state.view}.png`);
          toast(t('screenshotDone'));
        }
      } catch { toast(t('screenshotUnavailable')); } break;
  }
});

document.addEventListener('input', (event) => {
  const element = event.target;
  if (element.dataset.state) setState({ [element.dataset.state]: Number(element.value) }, 150);
  if (element.id === 'component-search') renderComponents();
});

document.addEventListener('change', (event) => {
  const element = event.target;
  if (element.dataset.visible) setState({ visible: { ...state.visible, [element.dataset.visible]: element.checked } });
  if (element.id === 'scenario-select') setState({ scenario: element.value });
  if (element.id === 'fieldlines-toggle') setState({ fieldLines: element.checked });
  if (element.dataset.state) flushPatch();
});

document.addEventListener('keydown', (event) => {
  const row = event.target.closest('[data-component]');
  if (row && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); setState({ selected: row.dataset.component }); }
  if (event.key === 'Escape') toggleAssembly(false);
});

$('#connection').addEventListener('click', () => { if (!streamLive) { streamerStarted = false; startStream(); } });
$('#remote-video').addEventListener('playing', () => { streamLive = true; renderConnection(); });
$('#remote-video').addEventListener('emptied', () => { streamLive = false; renderConnection(); });
for (const surface of [$('#remote-video'), $('#render-preview')]) {
  surface.addEventListener('pointerdown', (event) => { pointerStart = { x: event.clientX, y: event.clientY }; });
  surface.addEventListener('pointerup', (event) => {
    if (!pointerStart || event.button !== 0 || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 5) { pointerStart = null; return; }
    pointerStart = null;
    const rect = surface.getBoundingClientRect();
    const sourceWidth = surface.videoWidth || surface.naturalWidth || renderer.resolution?.[0] || 2560;
    const sourceHeight = surface.videoHeight || surface.naturalHeight || renderer.resolution?.[1] || 1440;
    const aspect = sourceWidth / sourceHeight;
    const width = Math.min(rect.width, rect.height * aspect), height = width / aspect;
    const x = (event.clientX - rect.left - (rect.width - width) / 2) / width;
    const y = (event.clientY - rect.top - (rect.height - height) / 2) / height;
    if (x >= 0 && x <= 1 && y >= 0 && y <= 1) action(measureMode ? 'measure' : 'pick', { x, y });
  });
}
$$('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));

applyLanguage();
try {
  manifest = await api('/api/manifest');
  renderComponents();
  renderDownloads();
} catch { toast(t('requestFailed')); }
poll();

