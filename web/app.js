const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const translations = {
  zh: {
    engineering: '工程', syntheticCase: '合成情景', heating: '辅助加热', neon: 'Ne 杂质注入', neonHint: '合成辐射冷却情景', divertorDesign: '偏滤器方案',
    fourCases: '四工况对比', sameInputs: '相同输入', fourCasesHint: '保持加热、冷却与磁平衡条件相同。', selectCaseHint: '选择卡片，在三维视口中查看该工况。',
    engineeringTools: '工程检查', thermalControls: '热工参数', powerHint: '基准热预算不含辅助加热；全部加热功率假定被吸收。', advancedViews: '工程场与装配', loadStudy: '独立负荷扫描', loadStudyHint: '无量纲准稳态负荷扫描。播放改变热负荷，不代表真实放电时间。',
    colorScale: '色标', logScale: '对数', linearScale: '线性', volumeDisplay: '体场显示', plasmaStyle: '等离子体', temperatureStyle: '温度', lineMotion: '方向示意动画',
    targetPeak: '靶板峰值热流', relativeNoNe: '相对同方案无 Ne 情景', equilibriumStages: '磁平衡快照', snapshotHint: '独立源快照 · 非连续瞬态',
    neOn: '有 Ne', neOff: '无 Ne', magneticStrength: '磁场强度', magneticHint: '箭头仅示意磁场方向，不表示粒子速度。', plasmaStyleHint: '粉紫色为等离子体展示示意；切换温度可查看合成 keV 场。', temperatureStyleHint: '源磁通形状约束的合成温度场，未经等离子体输运求解。',
    logHint: '零值中性灰 · 低于下限的正值取最低色阶', importedHint: '导入数据：{label} · 覆盖 {coverage}% · 灰色为无数据', fixedScale: '四工况共用固定色标', sourceGeometry: '源 CAD', syncing: '同步中', synchronized: '已同步', close: '关闭', positiveChange: '增加', negativeChange: '降低', versusNoNe: '相对无 Ne',
    stateRetrying: '正在重试工况更新', stateUnsaved: '工况尚未保存，点击重试', stateRejected: '工况参数被拒绝，请检查输入',
    volume: '等离子体', volumeError: '体积场生成失败，请切换模式后重试', volumePreparing: '体积渲染正在准备', plasmaHidden: '科学场模式下隐藏等离子体边界实体',
    design: '反应堆方案', conventional: '常规偏滤器', longleg: '长腿偏滤器', equilibrium: '磁平衡状态', eqRampup: '电流爬升', eqSof: '平顶开始', eqEof: '平顶结束', eqRampdown: '电流下降',
    differenceField: '三维差值场', deltaTemperature: '温度差', deltaHeatflux: '热流差', differenceNote: '当前工况减同方案无 Ne 工况，保持几何、磁平衡及其余热工参数相同。', powerBalance: '功率收支', powerInput: '当前输入热功率', surfacePower: '表面沉积', volumePower: '体积沉积', unresolvedPower: '未解析功率', balanceError: '收支误差', strikeUnresolved: '当前平衡未解析出有效靶板打击点', actionCancelled: '场景已变化，请重新操作', actionPending: '操作仍在处理中', fieldUpdating: '正在同步三维场', fieldSynchronized: '三维场已同步',
    digitalTwin: '聚变数字孪生', connecting: '正在连接', connected: 'RTX 实时串流', preview: 'RTX 预览', offline: '渲染器未连接', serverOffline: '服务未连接', fullscreen: '全屏',
    views: '视角', orbit: '环绕', assembly: '装配', assemblyTree: '模型装配树', measure: '测量', measureTitle: '部件尺寸与双点测量', reset: '重置', resetView: '恢复默认视角',
    searchComponents: '搜索部件', isolate: '隔离所选', showAll: '全部显示', selectComponent: '选择部件查看工程属性', explore: '探索', compare: '对比', settings: '工况设置', scenario: '运行工况',
    nominal: '额定运行', ramp: '热负荷爬升', lowflow: '低冷却流量', highload: '高热负荷', fusionPower: '基准热预算', coolantFlow: '冷却流量', inletTemperature: '冷却剂入口温度',
    visualization: '可视化方式', assemblyMode: '工程装配', temperature: '温度', heatflux: '热流密度', magnetic: '磁力线', slice: '截面场', adjustment: '可视化调整', cutaway: '剖开角度', explode: '装配爆炸', opacity: '不透明度', fieldLines: '叠加磁力线',
    compareTitle: '工况对比', compareDescription: '比较参考工况与当前工况的热管理响应。', baseline: '参考工况', candidate: '当前工况', compareNote: '同一几何模型 · 同一数据生成方法', trendTitle: '准稳态负荷扫描', surfaceTemperature: '峰值表面温度',
    readouts: '计算结果', peakTemperature: '峰值温度', peakHeatflux: '峰值热流', outletTemperature: '出口温度', coolingMargin: '温度裕量', fieldCompute: '场计算', export: '导出工况', screenshot: '截图',
    play: '播放 / 暂停', discharge: '负荷扫描', rampUp: '低负荷', flatTop: '中间负荷', rampDown: '名义负荷', dataProvenance: '数据来源与模型说明', initializing: '正在准备工程场景', initializingDetail: '加载 EU-DEMO 装配与 RTX 渲染器',
    dimensions: '工程尺寸', cadProvenance: '公开概念设计生成的反应堆装配。保留部件层级、材料和源模型信息。', engineeringDemo: '工程演示数据', fieldProvenance: '预制或简化模型生成的场数据用于交互展示；工况、单位和计算参数随导出文件提供。', renderProvenance: 'OpenUSD 场景通过本机 Kit 渲染，WebRTC 传输交互画面。',
    overview: '全堆总览', front: '正视图', top: '俯视图', section: '剖面视图', divertor: '偏滤器', overviewTitle: 'EU-DEMO 反应堆装配', frontTitle: '环向装配 · 正视', topTitle: '磁体与包层 · 俯视', sectionTitle: '堆内结构 · 剖面', divertorTitle: '偏滤器 · 热管理',
    overviewDescription: '公开 CAD 装配 · 交互工况与多物理场', frontDescription: 'TF / PF 线圈、真空室与等离子体边界', topDescription: '环向扇区、径向层级与维护通道', sectionDescription: '包层、屏蔽结构与真空边界', divertorDescription: '等离子体面对部件与热流分布',
    material: '材料', parts: '零部件', triangles: '三角面', source: '来源', dimensionsXYZ: '包围盒 X × Y × Z', downloadStep: '下载 STEP 源模型', downloadUsd: '下载 USD 场景', sourceCad: '源 CAD 文件', noResult: '等待计算结果', noHistory: '计算后显示负荷扫描曲线',
    selectFirst: '请先在装配树中选择部件', dimensionsHint: '所选部件的轴对齐包围盒尺寸，单位为米。', measureHint: '在三维视口中依次点击两个表面点。', startMeasure: '双点测量', clearMeasure: '清除测量', measurementStarted: '测量已开启，请在模型表面选择两个点', measuredDistance: '两点距离', noBounds: '当前部件尚无尺寸数据',
    exportDone: '已导出当前工况、计算结果与来源说明', screenshotDone: '已保存 RTX 渲染截图', screenshotUnavailable: '等待 RTX 画面后可保存截图', requestFailed: '操作未完成，请检查本地服务', updated: '工况已更新', noComponents: '没有匹配的部件', dataPending: '等待数据源信息', reference: '参考', gpuCompute: 'GPU 场计算', cpuCompute: 'CPU 场计算', liveRender: '实时渲染', connectHint: '点击重新连接串流', sourceEquilibrium: '公开平衡数据', heatfluxLimit: '色标上限 200 MW/m²', temperatureLimit: '色标上限 1,100 °C',
    compareAssembly: '查看当前工况', renderPending: 'RTX 正在加载场景', rendererError: '渲染器启动失败，检查运行日志', dimensionX: '宽度 X', dimensionY: '深度 Y', dimensionZ: '高度 Z', demoTimeline: '准稳态 · 合成工况',
  },
  en: {
    engineering: 'Engineering', syntheticCase: 'SYNTHETIC', heating: 'Auxiliary heating', neon: 'Ne impurity seeding', neonHint: 'Synthetic radiation-cooling scenario', divertorDesign: 'Divertor design',
    fourCases: 'FOUR-CASE COMPARISON', sameInputs: 'SAME INPUTS', fourCasesHint: 'Same heating, cooling & magnetic equilibrium.', selectCaseHint: 'Select a card to inspect the case in the 3D view.',
    engineeringTools: 'ENGINEERING INSPECTION', thermalControls: 'Thermal controls', powerHint: 'Base thermal budget excludes auxiliary heating; all heating is assumed absorbed.', advancedViews: 'Engineering fields & assembly', loadStudy: 'Independent load scan', loadStudyHint: 'Dimensionless quasi-steady load scan. Playback varies heat load and does not represent discharge time.',
    colorScale: 'Color scale', logScale: 'Log', linearScale: 'Linear', volumeDisplay: 'Volume display', plasmaStyle: 'Plasma', temperatureStyle: 'Temperature', lineMotion: 'Direction animation',
    targetPeak: 'Peak divertor heat flux', relativeNoNe: 'vs. same-design, no-Ne case', equilibriumStages: 'EQUILIBRIUM SNAPSHOTS', snapshotHint: 'Independent source snapshots · No transient solution',
    neOn: 'Ne ON', neOff: 'Ne OFF', magneticStrength: 'Magnetic strength', magneticHint: 'Direction only · Animation does not represent speed.', plasmaStyleHint: 'Pink-purple color is illustrative. Select Temperature for the synthetic keV field.', temperatureStyleHint: 'Synthetic temperature shaped by source flux; no plasma transport solve.',
    logHint: 'Zero: gray · Positive values below scale: lowest color', importedHint: 'Imported: {label} · {coverage}% coverage · gray = no data', fixedScale: 'One fixed scale for all four cases', sourceGeometry: 'SOURCE CAD', syncing: 'Syncing', synchronized: 'Synced', close: 'Close', positiveChange: 'increase', negativeChange: 'reduction', versusNoNe: 'vs. no Ne',
    stateRetrying: 'Retrying scenario update', stateUnsaved: 'Scenario not saved. Click to retry.', stateRejected: 'Scenario parameters were rejected. Check the input.',
    volume: 'Plasma volume', volumeError: 'Volume generation failed. Switch modes to retry.', volumePreparing: 'Volume rendering is preparing', plasmaHidden: 'The plasma boundary solid is hidden in field modes',
    design: 'Reactor design', conventional: 'Conventional divertor', longleg: 'Long-leg divertor', equilibrium: 'Magnetic equilibrium', eqRampup: 'Current ramp-up', eqSof: 'Start of flat-top', eqEof: 'End of flat-top', eqRampdown: 'Current ramp-down',
    differenceField: '3D DIFFERENCE FIELD', deltaTemperature: 'Temperature difference', deltaHeatflux: 'Heat-flux difference', differenceNote: 'Current minus the same-design no-Ne case, with identical equilibrium and other thermal inputs.', powerBalance: 'POWER BALANCE', powerInput: 'Current thermal input', surfacePower: 'Surface deposition', volumePower: 'Volume deposition', unresolvedPower: 'Unresolved power', balanceError: 'Balance error', strikeUnresolved: 'No valid target strike point resolved for this equilibrium', actionCancelled: 'The scene changed. Please retry the action.', actionPending: 'The action is still in progress.', fieldUpdating: 'Synchronizing 3D fields', fieldSynchronized: '3D fields synchronized',
    digitalTwin: 'Fusion Digital Twin', connecting: 'Connecting', connected: 'RTX LIVE STREAM', preview: 'RTX PREVIEW', offline: 'Renderer offline', serverOffline: 'Service offline', fullscreen: 'Fullscreen',
    views: 'VIEWS', orbit: 'ORBIT', assembly: 'Assembly', assemblyTree: 'ASSEMBLY TREE', measure: 'Measure', measureTitle: 'Component dimensions and point measurement', reset: 'Reset', resetView: 'Reset view',
    searchComponents: 'Search components', isolate: 'Isolate', showAll: 'Show all', selectComponent: 'Select a component to inspect its properties', explore: 'Explore', compare: 'Compare', settings: 'SETTINGS', scenario: 'Scenario',
    nominal: 'Nominal operation', ramp: 'Thermal load ramp', lowflow: 'Reduced coolant flow', highload: 'High heat load', fusionPower: 'Base thermal budget', coolantFlow: 'Coolant flow', inletTemperature: 'Coolant inlet temperature',
    visualization: 'VISUALIZATION', assemblyMode: 'Assembly', temperature: 'Temperature', heatflux: 'Heat flux', magnetic: 'Field lines', slice: 'Field section', adjustment: 'VISUALIZATION ADJUSTMENT', cutaway: 'Cutaway angle', explode: 'Explode', opacity: 'Opacity', fieldLines: 'Show magnetic field lines',
    compareTitle: 'SCENARIO COMPARISON', compareDescription: 'Thermal response of the reference and active operating scenarios.', baseline: 'BASELINE', candidate: 'CURRENT', compareNote: 'Same geometry · Same field-generation method', trendTitle: 'QUASI-STEADY LOAD SCAN', surfaceTemperature: 'Peak surface temperature',
    readouts: 'SIMULATION READOUTS', peakTemperature: 'Peak temperature', peakHeatflux: 'Peak heat flux', outletTemperature: 'Outlet temperature', coolingMargin: 'Thermal margin', fieldCompute: 'Field calculation', export: 'Export scenario', screenshot: 'Capture',
    play: 'Play / pause', discharge: 'LOAD SCAN', rampUp: 'Low load', flatTop: 'Intermediate', rampDown: 'Nominal load', dataProvenance: 'DATA & MODEL PROVENANCE', initializing: 'Preparing the engineering scene', initializingDetail: 'Loading EU-DEMO assembly and RTX renderer',
    dimensions: 'ENGINEERING DIMENSIONS', cadProvenance: 'Reactor assembly generated from an open concept design. Component hierarchy, materials and source references are retained.', engineeringDemo: 'Engineering demonstration data', fieldProvenance: 'Precomputed or reduced-model fields support the interactive demonstration. Scenarios, units and calculation inputs are included in exports.', renderProvenance: 'The OpenUSD scene is rendered locally by Kit and streamed interactively through WebRTC.',
    overview: 'Overview', front: 'Front', top: 'Top', section: 'Section', divertor: 'Divertor', overviewTitle: 'EU-DEMO reactor assembly', frontTitle: 'Toroidal assembly · Front', topTitle: 'Magnets & blanket · Top', sectionTitle: 'Internal structure · Section', divertorTitle: 'Divertor · Thermal response',
    overviewDescription: 'Public CAD assembly · Interactive scenarios & multiphysics fields', frontDescription: 'TF / PF coils, vacuum vessel and plasma boundary', topDescription: 'Toroidal sectors, radial layers and maintenance access', sectionDescription: 'Blanket, shielding and vacuum boundary', divertorDescription: 'Plasma-facing components and heat-flux distribution',
    material: 'Material', parts: 'Parts', triangles: 'Triangles', source: 'Source', dimensionsXYZ: 'Bounding box X × Y × Z', downloadStep: 'Download source STEP', downloadUsd: 'Download USD scene', sourceCad: 'Source CAD files', noResult: 'Waiting for calculation', noHistory: 'History appears after calculation',
    selectFirst: 'Select a component in the assembly tree first', dimensionsHint: 'Axis-aligned bounding-box dimensions of the selected component, in metres.', measureHint: 'Select two surface points in the 3D viewport.', startMeasure: 'Point-to-point', clearMeasure: 'Clear measurement', measurementStarted: 'Measurement enabled. Select two points on the model.', measuredDistance: 'Point-to-point distance', noBounds: 'Dimensions are not available for this component',
    exportDone: 'Scenario, results and provenance exported', screenshotDone: 'RTX render saved', screenshotUnavailable: 'Capture is available after the RTX image arrives', requestFailed: 'Action failed. Check the local service.', updated: 'Scenario updated', noComponents: 'No matching components', dataPending: 'Waiting for source metadata', reference: 'Reference', gpuCompute: 'GPU field calculation', cpuCompute: 'CPU field calculation', liveRender: 'Live rendering', connectHint: 'Click to reconnect the stream', sourceEquilibrium: 'Public equilibrium data', heatfluxLimit: 'Color scale capped at 200 MW/m²', temperatureLimit: 'Color scale capped at 1,100 °C',
    compareAssembly: 'View current scenario', renderPending: 'RTX is loading the scene', rendererError: 'Renderer failed to start. Check runtime logs.', dimensionX: 'Width X', dimensionY: 'Depth Y', dimensionZ: 'Height Z', demoTimeline: 'QUASI-STEADY · SYNTHETIC',
  },
};

let language = localStorage.getItem('fusion-language') === 'en' ? 'en' : 'zh';
let manifest = { components: [] };
let state = { view: 'overview', tab: 'explore', mode: 'volume', scenario: 'nominal', power: 2000, flow: 1, inlet: 300, phase: 1, cutaway: 80, explode: 0, opacity: 1, visible: {}, selected: '', fieldLines: true, orbit: false, playing: false };
let result = {};
let renderer = {};
let revision = -1;
let streamLive = false;
let previewReady = false;
let serviceReady = false;
let pendingPatch = {};
let inflightPatch = {};
let patchTimer;
let sendingPatch = false;
let lastPatchSent = -Infinity;
let patchRetries = 0;
let patchRetryAt = 0;
let patchPaused = false;
let patchRecoveryObserved = false;
let previewLoading = false;
let lastPreview = 0;
let streamerStarted = false;
let toastTimer;
let measureMode = false;
let measurementGeneration = 0;
let pointerStart = null;
let lastMeasuredDistance = null;
let actionTail = Promise.resolve();
let activeActions = 0;
let serverEpoch = null;
let committedGeometry = null;

state.design = 'conventional';
state.equilibrium = 'sof';
state.heating = 50;
state.neon = false;
state.heatScale = 'log';
state.volumeStyle = 'plasma';
state.lineMotion = true;

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

const cameraViews = ['overview', 'front', 'top', 'section', 'divertor'];

function renderCameras() {
  $('#camera-buttons').innerHTML = cameraViews.map((view, index) => `<button class="camera-button ${state.view === view ? 'active' : ''}" data-view="${view}" title="${t(view)}" aria-label="${t(view)}" aria-pressed="${state.view === view}"><img src="/assets/ui/cameras/${view}.png" alt=""><span class="view-number">0${index + 1}</span><span class="view-label">${t(view)}</span></button>`).join('');
}

function getDimensions(component) {
  const bounds = component?.bounds_m;
  return bounds ? bounds[1].map((value, index) => Math.abs(value - bounds[0][index])) : null;
}

function renderComponents() {
  const query = $('#component-search').value.trim().toLowerCase();
  const components = manifest.components || [];
  const visible = components.filter((component) => [component.name_en, component.name_zh, component.id].some((value) => String(value || '').toLowerCase().includes(query)));
  const partCount = components.reduce((sum, component) => sum + (component.part_count || 0), 0);
  $('#assembly-count').textContent = `${number(components.length)} ${language === 'zh' ? '系统' : 'systems'} / ${number(partCount)} ${t('parts')}`;
  $('#component-tree').innerHTML = visible.length ? visible.map((component) => `<div class="component-row ${state.selected === component.id ? 'selected' : ''}" data-component="${esc(component.id)}" role="button" tabindex="0" aria-pressed="${state.selected === component.id}"><input type="checkbox" data-visible="${esc(component.id)}" ${state.visible?.[component.id] !== false && (component.id !== 'plasma' || state.mode === 'assembly') ? 'checked' : ''} ${component.id === 'plasma' && state.mode !== 'assembly' ? `disabled title="${t('plasmaHidden')}"` : ''} aria-label="${t('showAll')} ${esc(componentName(component))}"><svg viewBox="0 0 20 20"><path d="m10 2 7 4v8l-7 4-7-4V6zm-7 4 7 4 7-4m-7 4v8"/></svg><span>${esc(componentName(component))}</span><small>${number(component.part_count)}</small></div>`).join('') : `<p class="empty-chart">${t('noComponents')}</p>`;
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
  const links = [];
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
  const label = patchPaused ? 'stateUnsaved' : streamLive ? 'connected' : previewReady ? 'preview' : serviceReady ? 'connecting' : 'serverOffline';
  connection.classList.toggle('online', streamLive);
  connection.classList.toggle('error', !serviceReady || patchPaused);
  $('span', connection).textContent = t(label);
  connection.title = t(patchPaused ? 'stateUnsaved' : 'connectHint');
  $('#viewport').classList.toggle('live', streamLive);
  $('#loading-state').hidden = streamLive || previewReady;
  const rendererStatus = String(renderer.status || '').toLowerCase();
  $('#loading-detail').textContent = renderer.error || rendererStatus.includes('error') ? t('rendererError') : t(serviceReady ? 'renderPending' : 'initializingDetail');
  const gpu = result.gpu_name || renderer.gpu;
  $('#gpu-label').textContent = typeof gpu === 'string' ? gpu : 'GPU —';
}

function colorGradient(map) {
  const colors = map?.colors || map?.rgba;
  if (!colors?.length) return '';
  return `linear-gradient(90deg,${colors.map((rgba, index) => `rgb(${rgba.slice(0, 3).map(value => Math.round(value * 255)).join(' ')}) ${(map.positions?.[index] ?? index / (colors.length - 1)) * 100}%`).join(',')})`;
}

function heatRange() {
  return result.color_ranges?.[state.heatScale === 'log' ? 'heatflux_log' : 'heatflux'] || (state.heatScale === 'log' ? [0.01, 200] : [0, 200]);
}

function renderLegend() {
  const modes = { temperature: ['temperature', '°C', 300, 1100], heatflux: ['heatflux', 'MW/m²', 0, 200], delta_temperature: ['deltaTemperature', '°C', -1, 1], delta_heatflux: ['deltaHeatflux', 'MW/m²', -1, 1], slice: ['temperature', 'keV', 0, 40], volume: ['temperature', 'keV', 0, 40], magnetic: ['magneticStrength', 'T', 2, 12] };
  const mode = state.mode;
  const legend = modes[mode];
  const showLegend = Boolean(legend) && (mode !== 'volume' || (state.volumeStyle === 'temperature' && renderer.volume_style === 'temperature'));
  $('#heat-options').hidden = mode !== 'heatflux';
  $('#volume-options').hidden = mode !== 'volume';
  $('#magnetic-options').hidden = mode !== 'magnetic';
  $('#field-legend').hidden = !showLegend;
  const imported = result.imported_surface?.mode === mode ? result.imported_surface : null;
  const note = imported ? 'importedHint' : mode === 'magnetic' ? 'magneticHint' : mode === 'volume' ? (state.volumeStyle === 'plasma' ? 'plasmaStyleHint' : 'temperatureStyleHint') : mode === 'slice' ? 'temperatureStyleHint' : mode === 'heatflux' && state.heatScale === 'log' ? 'logHint' : null;
  $('#mode-note').hidden = !note;
  $('#mode-note').textContent = imported ? t(note).replace('{label}', imported.label).replace('{coverage}', number(imported.coverage * 100)) : note ? t(note) : '';
  $$('[data-heat-scale]').forEach(button => { button.classList.toggle('active', button.dataset.heatScale === state.heatScale); button.setAttribute('aria-pressed', button.dataset.heatScale === state.heatScale); });
  $$('[data-volume-style]').forEach(button => { button.classList.toggle('active', button.dataset.volumeStyle === state.volumeStyle); button.setAttribute('aria-pressed', button.dataset.volumeStyle === state.volumeStyle); });
  if (!showLegend) return;
  $('#legend-title').textContent = t(legend[0]);
  $('#legend-unit').textContent = legend[1];
  const bar = $('.colormap');
  bar.classList.toggle('diverging', mode.startsWith('delta_'));
  bar.classList.toggle('heat-colormap', mode === 'heatflux');
  const colorMap = mode === 'volume' ? renderer.volume_colormap : result.color_maps?.[mode];
  bar.style.background = colorGradient(colorMap);
  const range = mode === 'heatflux' ? heatRange() : mode === 'volume' ? (renderer.volume_colormap?.domain || result.color_ranges?.slice || [0, 40]) : (result.color_ranges?.[mode] || legend.slice(2));
  const isLog = mode === 'heatflux' && state.heatScale === 'log';
  const ticks = isLog ? [range[0], ...[0.1, 1, 10].filter(value => value > range[0] && value < range[1]), range[1]] : [range[0], (range[0] + range[1]) / 2, range[1]];
  $('#legend-ticks').innerHTML = ticks.map(value => {
    const position = isLog ? (Math.log10(value) - Math.log10(range[0])) / (Math.log10(range[1]) - Math.log10(range[0])) : (value - range[0]) / (range[1] - range[0]);
    return `<span style="left:${position * 100}%">${number(value, Math.abs(value) > 0 && Math.abs(value) < 1 ? 2 : Number.isInteger(value) ? 0 : 1)}</span>`;
  }).join('');
}

function fieldsSynchronized() {
  return renderer.ready && result.field_ref?.key && renderer.applied_field_key === result.field_ref.key &&
    !sendingPatch && !Object.keys(pendingPatch).length && renderer.applied_revision >= revision &&
    (state.mode !== 'volume' || (!renderer.volume_pending && !renderer.volume_error && renderer.applied_volume_field_key === result.field_ref.key && renderer.volume_mask_angle === state.cutaway));
}

function renderPowerBudget() {
  const budget = result.power_budget;
  if (!budget) { $('#power-budget').textContent = t('noResult'); return; }
  const rows = [['powerInput', 'requested_thermal_MW'], ['surfacePower', 'surface_absorbed_MW'], ['volumePower', 'volume_absorbed_MW'], ['unresolvedPower', 'unresolved_MW'], ['balanceError', 'closure_residual_MW']];
  const volume = state.mode === 'volume';
  const synchronized = fieldsSynchronized();
  $('#power-budget').innerHTML = rows.map(([label, key]) => `<div class="property-row"><span>${t(label)}</span><span>${number(budget[key], 2)} MW</span></div>`).join('') +
    `${budget.unresolved_MW > 0.01 ? `<p class="budget-warning">${t('strikeUnresolved')}</p>` : ''}<p class="field-sync ${synchronized ? 'synchronized' : ''}">${t(volume && renderer.volume_error ? 'volumeError' : synchronized ? 'fieldSynchronized' : 'fieldUpdating')}</p>`;
}

function renderResults() {
  const outputs = { 'kpi-temperature': ['peak_temperature_C', 0], 'kpi-heatflux': ['peak_heatflux_MW_m2', 2], 'kpi-outlet': ['outlet_temperature_C', 0], 'kpi-margin': ['cooling_margin_C', 0] };
  for (const [id, [key, decimals]] of Object.entries(outputs)) $(`#${id}`).textContent = number(result[key], decimals);
  $('#kpi-margin').style.color = result.cooling_margin_C < 0 ? '#e2a08c' : '';
  $('#compute-badge').textContent = result.compute_backend || '—';
  $('#gpu-time').textContent = result.gpu_ms != null ? `${number(result.gpu_ms, 2)} ms` : '—';
  const sourceLabel = ['synthetic_thermal_bluemira_equilibrium', 'synthetic_demo_source_geometry_equilibrium'].includes(result.source_label) ? (language === 'zh' ? '合成热预算与简化传热模型 / Bluemira 概念几何与磁平衡' : 'Synthetic thermal budget and reduced heat-transfer model / Bluemira concept geometry and equilibrium') : result.source_label || manifest.source_label || t('dataPending');
  const assumptions = result.assumptions || {};
  const assumptionLabels = { thermal: ['传热模型', 'Thermal model'], coolant: ['冷却回路', 'Coolant'], budget: ['功率预算', 'Power budget'], radiation: ['辐射沉积', 'Radiation deposition'], target: ['靶板热流', 'Target heat flux'], history: ['扫描坐标', 'Scan coordinate'], limit: ['演示阈值', 'Demonstration threshold'], magnetics: ['磁平衡', 'Magnetic equilibrium'], plasma_slice: ['等离子体截面', 'Plasma section'], neon: ['Ne 情景', 'Ne scenario'], color: ['色标', 'Color scales'] };
  const assumptionChinese = {
    'power is the base thermal budget excluding auxiliary heating. At scan fraction L: total=(power+heating)*L; blanket volume=.8*power*L; plasma=(.2*power+heating)*L. Core radiation=.65*plasma; SOL radiation=.30 (Ne off) or .80 (Ne on) of separatrix power, wall particles=.03, targets receive the remainder, inner/outer 30/70%. All heating is assumed absorbed; no solved fusion source': 'power 为不含辅助加热的基准热预算。扫描负荷比例为 L 时，总输入=(power+heating)×L；包层体积热源=0.8×power×L；等离子体通道=(0.2×power+heating)×L。核心辐射占等离子体通道的 65%；SOL 辐射占分离面功率的 30%（无 Ne）或 80%（有 Ne），主壁粒子占 3%，其余进入靶板，内外靶板按 30/70% 分配。全部加热假定被吸收，未求解聚变源项。',
    'Synthetic Eich widths: lambda_q=6 mm, S=2 mm, both divided by hotspot. Ne-on multipliers 1.5/2; longleg S multiplier 1.35. Flux mapping and incidence at source psi=1 intersections, local +/-0.75 m footprint; no 3D shadowing or detached SOL solution': '合成 Eich 宽度 λq=6 mm、S=2 mm，均除以热点系数。Ne 情景分别乘以 1.5 和 2，长腿方案的 S 再乘以 1.35。在源 ψ=1 交点进行磁通映射并考虑入射角，局部热斑范围为 ±0.75 m；未求解三维遮挡或脱靶 SOL。',
    'Boolean radiation/spreading hypothesis; no injection rate, impurity transport, radiation-front solve or measured detachment claim. Four cases share all controls except design/neon; differences use same design/equilibrium/controls with neon off': 'Ne 开关对应辐射与热斑展宽假设，不包含注入率、杂质输运或辐射前沿求解，也不代表实测脱靶。四工况仅改变方案和 Ne 开关；差值场采用相同方案、平衡及其余参数的无 Ne 工况为基准。',
    'Fixed linear heatflux 0..200 and log10 0.01..200 MW/m2. Nonpositive/no-data samples are neutral; positive log values below minimum clamp to lower color. Out-of-range counts are explicit; no per-case autoscaling': '热流固定使用 0–200 MW/m² 线性色标或 0.01–200 MW/m² 对数色标。非正值和缺失值使用中性灰；低于对数下限的正值使用最低色阶。记录超范围数量，各工况不单独自动缩放色标。',
    'Synthetic source-flux-shaped core profile: 25 keV * (.2*power+heating)/450 * load_fraction, with a prescribed .95 multiplier for Ne on; 193x225 RZ sampling, not a plasma transport solution': '按源磁通形状构造合成核心温度：25 keV×(0.2×power+heating)/450×负荷比例；Ne 开启时再乘以 0.95。RZ 采样为 193×225，未求解等离子体输运。',
    'Synthetic quasi-steady wall resistance; prescribed load scan, no time-dependent heat transport or qualified material model': '采用合成壁面热阻的准稳态负荷扫描，未求解瞬态热输运，材料模型未经工程评定。',
    'Absorbed surface plus assumed blanket volume heat only; helium cp=5200 J/(kg K), 3500 kg/s times flow, 85/15% circuit split; unresolved power excluded': '回路吸热包含表面沉积与假定包层体积热源，不包含未解析功率。氦比热 5,200 J/(kg·K)，总质量流量为 3,500 kg/s 乘流量系数，两回路按 85/15% 分配。',
    'Input is effective thermal power, not fusion power. Synthetic split: 80% blanket volume, 20% plasma-surface channel; 65% core radiation, then 70% SOL radiation, 3% wall particles and 27% targets; target inner/outer 30/70%': '输入代表有效热功率。合成预算分配：80% 包层体积热源，20% 等离子体表面通道；后者 65% 分配给核心辐射，余量再按 70% SOL 辐射、3% 主壁粒子、27% 靶板分配；内外靶板按 30/70% 分配。',
    'Uniform area deposition split 90/10% wall/divertor; no photon transport or neutron transport calculation': '辐射按面积均匀沉积，主壁／偏滤器按 90/10% 分配；未求解光子或中子输运。',
    'Eich upstream profile with synthetic lambda_q=6 mm, S=2 mm divided by hotspot, flux mapping and incidence; local +/-0.75 m neighborhood at a source psi=1 intersection; no 3D shadowing or detached SOL solution': '使用 Eich 上游轮廓，合成宽度 λq=6 mm、S=2 mm 随热点系数调整；通过磁通映射及入射角，在源 ψ=1 交点附近 ±0.75 m 建立局部热斑；未求解三维遮挡和脱靶 SOL。',
    'Selected Bluemira axisymmetric equilibrium, Bphi=fvac/R approximation; cached per equilibrium; no discrete TF ripple': '使用所选 Bluemira 轴对称平衡，Bφ=fvac/R，按平衡缓存；未包含离散 TF 纹波。',
    'Synthetic 25 keV core profile shaped by selected source normalized poloidal flux': '依据所选平衡的归一化极向磁通，构造 25 keV 核心温度的合成剖面。',
    'Dimensionless quasi-steady load scan, phase in [0,1]; no elapsed-time coordinate; equilibria are independently selected snapshots': '无量纲准稳态负荷扫描，扫描进度为 0–1；磁平衡为独立选择的状态快照。',
    'Synthetic surface heat-flux distribution and wall thermal resistance; not normalized as a conservative full-reactor heat solution': '合成表面热流分布与壁面热阻模型；未按全堆功率守恒进行归一化。',
    'Separate assumed helium circuit energy balance: cp=5200 J/(kg K), nominal flow=3500 kg/s': '采用独立假定的氦冷却回路能量平衡：比热 5,200 J/(kg·K)，额定质量流量 3,500 kg/s。',
    '900 degC demonstration threshold; not a material qualification limit': '900 °C 为演示温度阈值，未用于材料合格评定。',
    'Bluemira reference equilibrium, Bphi=fvac/R approximation; unchanged by thermal controls': '使用 Bluemira 参考平衡与 Bφ = fvac/R 近似；热负荷和冷却参数不改变磁平衡。',
    'Synthetic 25 keV core profile shaped by source normalized poloidal flux': '依据源数据归一化极向磁通构造合成的 25 keV 核心温度剖面。',
  };
  const sourceMarkup = `${esc(sourceLabel)}${Object.keys(assumptions).length ? `<details class="assumptions"><summary>${language === 'zh' ? '计算假设与适用范围' : 'Calculation assumptions & scope'}</summary>${Object.entries(assumptions).map(([key, value]) => `<p><strong>${esc(assumptionLabels[key]?.[language === 'zh' ? 0 : 1] || key)}</strong><br>${esc(language === 'zh' ? assumptionChinese[value] || value : value)}</p>`).join('')}</details>` : ''}`;
  if ($('#source-description').dataset.content !== sourceMarkup) { $('#source-description').innerHTML = sourceMarkup; $('#source-description').dataset.content = sourceMarkup; }
}

function storyCasesReady() {
  const controls = result.story?.comparison_controls;
  return controls && result.scenario_label === state.scenario && ['power', 'heating', 'flow', 'inlet', 'phase', 'equilibrium'].every(key => controls[key] === state[key]);
}

function signedPercent(value) {
  return value == null ? '—' : `${value > 0 ? '+' : ''}${number(value, 1)}%`;
}

function renderStory() {
  const selectedCase = storyCasesReady() ? result.story.cases?.find(item => item.design === state.design && item.neon === state.neon) : null;
  $('#story-peak').textContent = number(selectedCase?.peak_divertor_heatflux_MW_m2, 2);
  $('#story-relative').textContent = signedPercent(selectedCase?.relative_no_neon_percent);
  const synchronized = fieldsSynchronized();
  $('#story-sync').textContent = t(synchronized ? 'synchronized' : 'syncing');
  $('#story-sync').classList.toggle('synchronized', Boolean(synchronized));
}

function renderComparison() {
  const cases = storyCasesReady() ? result.story.cases : [];
  const container = $('#comparison-cases');
  if (!container.children.length) {
    container.innerHTML = ['conventional', 'longleg'].flatMap(design => [false, true].map(neon =>
      `<button class="case-card" data-case-design="${design}" data-case-neon="${neon}"><span class="case-design"></span><span class="case-neon"></span><div class="case-value"><strong></strong><small>MW/m²</small></div><span class="case-delta"></span></button>`
    )).join('');
  }
  $$('[data-case-design]', container).forEach(button => {
    const design = button.dataset.caseDesign, neon = button.dataset.caseNeon === 'true';
    const item = cases?.find(candidate => candidate.design === design && candidate.neon === neon);
    const active = state.design === design && state.neon === neon;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active);
    button.setAttribute('aria-busy', !item);
    $('.case-design', button).textContent = t(design);
    $('.case-neon', button).textContent = t(neon ? 'neOn' : 'neOff');
    $('.case-value strong', button).textContent = number(item?.peak_divertor_heatflux_MW_m2, 2);
    $('.case-delta', button).textContent = `${signedPercent(item?.relative_no_neon_percent)} · ${t('versusNoNe')}`;
  });
  const range = heatRange();
  $('#comparison-scale').textContent = `${t('fixedScale')} · ${number(range[0], range[0] < 1 && range[0] > 0 ? 2 : 0)}–${number(range[1])} MW/m² · ${t(state.heatScale === 'log' ? 'logScale' : 'linearScale')}`;
}

function renderCameraSelection() {
  $$('[data-view]').forEach(button => {
    button.classList.toggle('active', button.dataset.view === state.view);
    button.setAttribute('aria-pressed', button.dataset.view === state.view);
  });
}

function renderHistory() {
  const history = result.history;
  const chart = $('#history-chart');
  const entries = (history || []).map((item) => ({ x: item.phase, y: item.peak_temperature_C }));
  if (entries.length < 2) { chart.innerHTML = `<span class="empty-chart">${t('noHistory')}</span>`; return; }
  const xs = entries.map((item) => item.x), ys = entries.map((item) => item.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const points = entries.map((item) => `${8 + (item.x - minX) / (maxX - minX || 1) * 272},${95 - (item.y - minY) / (maxY - minY || 1) * 74}`).join(' ');
  chart.innerHTML = `<svg viewBox="0 0 290 115" role="img" aria-label="${t('surfaceTemperature')}"><path d="M8 20h272M8 58h272M8 96h272" stroke="#ffffff14" stroke-width=".7"/><polyline points="${points}" fill="none" stroke="#8db96d"/><text x="8" y="111" fill="#728569" stroke="none" font-size="12">${number(minX, 1)}</text><text x="280" y="111" fill="#728569" stroke="none" font-size="12" text-anchor="end">${number(maxX, 1)}</text><text x="280" y="13" fill="#9ab48b" stroke="none" font-size="12" text-anchor="end">${number(maxY)} °C</text></svg>`;
}

function render() {
  if (manifest.active_design !== state.design && manifest.design_components?.[state.design]) {
    manifest.components = manifest.design_components[state.design];
    manifest.active_design = state.design;
    renderComponents();
    renderDownloads();
  }
  $$('[data-tab]').forEach((button) => { button.classList.toggle('active', button.dataset.tab === state.tab); button.setAttribute('aria-selected', button.dataset.tab === state.tab); });
  for (const tab of ['explore', 'compare', 'engineering']) $(`#${tab}-panel`).hidden = state.tab !== tab;
  $$('[data-mode]').forEach((button) => { button.classList.toggle('active', button.dataset.mode === state.mode); button.setAttribute('aria-pressed', button.dataset.mode === state.mode); });
  $('[data-mode="volume"]').disabled = !renderer.rtwt_ready;
  $('[data-mode="volume"]').title = renderer.rtwt_ready ? '' : t('volumePreparing');
  renderCameraSelection();
  $$('[data-state]').forEach((input) => {
    const key = input.dataset.state;
    if (document.activeElement !== input) input.value = state[key];
    input.style.setProperty('--progress', `${(Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min)) * 100}%`);
    const output = $(`#${key}-value`);
    if (output) output.innerHTML = sliderValue(key);
  });
  $('#scenario-select').value = state.scenario;
  $$('[data-design]').forEach(button => { button.classList.toggle('active', button.dataset.design === state.design); button.setAttribute('aria-pressed', button.dataset.design === state.design); });
  $$('[data-heating]').forEach(button => { button.classList.toggle('active', Number(button.dataset.heating) === state.heating); button.setAttribute('aria-pressed', Number(button.dataset.heating) === state.heating); });
  $$('[data-equilibrium]').forEach(button => { button.classList.toggle('active', button.dataset.equilibrium === state.equilibrium); button.setAttribute('aria-pressed', button.dataset.equilibrium === state.equilibrium); });
  $('#neon-toggle').checked = state.neon;
  $('#line-motion-toggle').checked = state.lineMotion;
  $('#equilibrium-select').value = state.equilibrium;
  $('#fieldlines-toggle').checked = state.fieldLines;
  $('#orbit-button').classList.toggle('active', state.orbit);
  $('#play-button').classList.toggle('playing', state.playing);
  $('#play-button').setAttribute('aria-pressed', state.playing);
  $('#view-title').textContent = t(`${state.view}Title`);
  $('#view-subtitle').textContent = t(`${state.view}Description`);
  renderLegend();
  renderConnection();
  renderResults();
  renderPowerBudget();
  renderComparison();
  renderStory();
  renderHistory();
  if ($('#measure-dialog').open) renderMeasurement();
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) { const error = new Error(`${response.status} ${path}`); error.status = response.status; throw error; }
  return response.json();
}

function resetMeasurement() {
  measurementGeneration += 1;
  measureMode = false;
  lastMeasuredDistance = null;
  renderer.measurement = null;
  $('#measure-button').classList.remove('active');
}

function applySnapshot(snapshot) {
  if (snapshot.server_epoch && snapshot.server_epoch !== serverEpoch) { serverEpoch = snapshot.server_epoch; revision = -1; }
  if (snapshot.revision != null && snapshot.revision < revision) return;
  revision = snapshot.revision ?? revision;
  const previousSelected = state.selected;
  const previousVisibility = JSON.stringify(state.visible);
  const previousDesign = state.design;
  const previousEquilibrium = state.equilibrium;
  const committedGeometryChanged = snapshot.state && committedGeometry &&
    ['design', 'equilibrium'].some(key => snapshot.state[key] !== committedGeometry[key]);
  if (snapshot.state) committedGeometry = { design: snapshot.state.design, equilibrium: snapshot.state.equilibrium };
  const previousMode = state.mode;
  const previousRendererEpoch = renderer.renderer_epoch;
  state = { ...state, ...(snapshot.state || {}), ...inflightPatch, ...pendingPatch };
  result = snapshot.result || result;
  renderer = snapshot.renderer || renderer;
  if (previousDesign !== state.design && manifest.design_components?.[state.design]) {
    manifest.components = manifest.design_components[state.design];
    renderer.measurement = null;
    renderDownloads();
  }
  const geometryPending = snapshot.state && ['design', 'equilibrium'].some(key => state[key] !== snapshot.state[key]);
  const fieldGeometry = result.field_ref;
  const rendererGeometryPending = fieldGeometry && (renderer.topology_key !== fieldGeometry.topology_key || renderer.equilibrium_key !== fieldGeometry.equilibrium_key);
  if (committedGeometryChanged || geometryPending || rendererGeometryPending || previousDesign !== state.design ||
      previousEquilibrium !== state.equilibrium || (previousRendererEpoch && previousRendererEpoch !== renderer.renderer_epoch)) resetMeasurement();
  if (!('selected' in inflightPatch) && !('selected' in pendingPatch) && renderer.selected && renderer.applied_revision >= revision && state.selected !== renderer.selected) {
    state.selected = renderer.selected;
    pendingPatch.selected = renderer.selected;
    clearTimeout(patchTimer);
    patchTimer = setTimeout(flushPatch, 0);
  }
  serviceReady = true;
  if (previousMode !== state.mode || previousDesign !== state.design || previousSelected !== state.selected || previousVisibility !== JSON.stringify(state.visible)) renderComponents();
  render();
}

function setState(patch, delay = 0) {
  if (['design', 'equilibrium'].some(key => key in patch && patch[key] !== state[key])) resetMeasurement();
  if (patchPaused) resumePatch();
  pendingPatch = { ...pendingPatch, ...patch };
  state = { ...state, ...patch };
  render();
  if ('selected' in patch || 'visible' in patch || 'mode' in patch) renderComponents();
  schedulePatch(delay);
}

function schedulePatch(interval = 0) {
  clearTimeout(patchTimer);
  if (patchPaused) { patchTimer = null; return; }
  const now = performance.now();
  patchTimer = setTimeout(flushPatch, Math.max(0, interval - (now - lastPatchSent), patchRetryAt - now));
}

function resumePatch() {
  patchRetries = 0;
  patchRetryAt = 0;
  patchPaused = false;
  patchRecoveryObserved = false;
  if (Object.keys(pendingPatch).length) schedulePatch();
}

function retryableStateError(error) {
  const status = error.status || Number(String(error.message).match(/HTTP Error (\d{3})/)?.[1]);
  if (status) return status >= 500 || status === 408 || status === 429;
  if (error.rejected) return /URLError|TimeoutError|ConnectionError|unavailable/i.test(error.message);
  return !/^(ValueError|TypeError):/.test(error.message);
}

async function flushPatch() {
  clearTimeout(patchTimer);
  patchTimer = null;
  if (sendingPatch || patchPaused || !Object.keys(pendingPatch).length) return;
  if (performance.now() < patchRetryAt) { schedulePatch(); return; }
  const patch = pendingPatch;
  pendingPatch = {};
  inflightPatch = patch;
  sendingPatch = true;
  lastPatchSent = performance.now();
  try {
    let snapshot;
    if (streamLive && renderer.rtwt_ready && window.FusionStreamer?.connected) {
      const response = await window.FusionStreamer.request('fusion_set_state', { state: patch }, 45000);
      if (!response?.accepted) {
        const error = new Error(response?.error || 'RTX state request was rejected');
        error.rejected = true;
        throw error;
      }
      snapshot = await api('/api/state');
    } else {
      snapshot = await api('/api/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
    }
    inflightPatch = {};
    patchRetries = 0;
    patchRetryAt = 0;
    patchRecoveryObserved = false;
    applySnapshot(snapshot);
  }
  catch (error) {
    if (retryableStateError(error)) {
      pendingPatch = { ...patch, ...pendingPatch };
      patchRetries += 1;
      patchPaused = patchRetries > 2;
      patchRetryAt = performance.now() + (patchRetries === 1 ? 250 : 1000);
      serviceReady = false;
      toast(t(patchPaused ? 'stateUnsaved' : 'stateRetrying'));
    } else {
      patchRetries = 0;
      patchRetryAt = 0;
      toast(t('stateRejected'));
    }
    renderConnection();
  }
  finally {
    inflightPatch = {};
    sendingPatch = false;
    if (Object.keys(pendingPatch).length && !patchPaused) schedulePatch(50);
  }
}

async function action(type, extra = {}) {
  const requestId = crypto.randomUUID();
  const payload = { type, ...extra, request_id: requestId, server_epoch: serverEpoch, renderer_epoch: renderer.renderer_epoch };
  if ('x' in extra || 'y' in extra) {
    payload.topology_key = renderer.topology_key;
    payload.interaction_key = renderer.interaction_key;
  }
  const accepted = actionTail.then(() => api('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }));
  actionTail = accepted.catch(() => {});
  activeActions += 1;
  try {
    let record = await accepted;
    const deadline = Date.now() + 30000;
    while (record.status === 'pending' || record.status === 'running') {
      if (Date.now() > deadline) { toast(t('actionPending')); return null; }
      await new Promise((resolve) => setTimeout(resolve, 100));
      record = await api(`/api/actions/${encodeURIComponent(requestId)}`);
    }
    if (record.status !== 'completed') { toast(t(record.status === 'cancelled' ? 'actionCancelled' : 'requestFailed')); return null; }
    applySnapshot(await api('/api/state'));
    return record;
  } catch (error) { toast(t(error.status === 409 ? 'actionCancelled' : 'requestFailed')); return null; }
  finally { activeActions -= 1; }
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
  const distance = measurement?.distance_m;
  $('#measurement-content').innerHTML = `<h3>${esc(component ? componentName(component) : t('dimensions'))}</h3>${dimensions ? `<p>${t('dimensionsHint')}</p><div class="dimension-cards">${dimensions.map((value, index) => `<div><span>${t(['dimensionX', 'dimensionY', 'dimensionZ'][index])}</span><strong>${number(value, 2)}</strong> <small>m</small></div>`).join('')}</div>` : `<p>${t(component ? 'noBounds' : 'selectComponent')}</p>`}${distance != null ? `<p>${t('measuredDistance')}</p><div class="measure-result">${number(distance, 3)} <small>m</small></div>` : ''}<p>${t('measureHint')}</p><div class="measurement-actions"><button class="outline-button" id="start-measure-button">${t('startMeasure')}</button><button class="outline-button" id="clear-measure-button">${t('clearMeasure')}</button></div>`;
}

function openMeasurement() {
  renderMeasurement();
  $('#measure-dialog').showModal();
}

async function startMeasurement() {
  resetMeasurement();
  const generation = measurementGeneration;
  const response = await action('measure_start');
  if (!response || generation !== measurementGeneration) return;
  measureMode = true;
  $('#measure-dialog').close();
  $('#measure-button').classList.add('active');
  toast(t('measurementStarted'));
}

async function selectViewportPoint(x, y) {
  const measuring = measureMode;
  const generation = measurementGeneration;
  const completed = await action(measuring ? 'measure' : 'pick', { x, y });
  const measurement = completed?.result?.measurement;
  if (measuring && generation === measurementGeneration && measureMode && measurement?.type === 'distance') {
    renderer.measurement = measurement;
    measureMode = false;
    lastMeasuredDistance = measurement.distance_m;
    $('#measure-button').classList.remove('active');
    openMeasurement();
  }
}

function startStream() {
  if (!window.FusionStreamer || streamerStarted) return;
  streamerStarted = true;
  window.FusionStreamer.connect({
    onConnected: () => { streamLive = true; if (patchPaused) resumePatch(); renderConnection(); },
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
    if (!sendingPatch && (!Object.keys(pendingPatch).length || patchPaused)) {
      applySnapshot(await api('/api/state'));
      if (patchPaused && patchRecoveryObserved) resumePatch();
    }
    updatePreview();
    if (!streamerStarted && serviceReady && renderer.ready) startStream();
  } catch { patchRecoveryObserved = true; serviceReady = false; renderConnection(); }
  setTimeout(poll, document.hidden ? 2500 : activeActions || state.playing ? 250 : 1000);
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  const componentRow = event.target.closest('[data-component]');
  if (componentRow && !event.target.matches('input')) setState({ selected: componentRow.dataset.component });
  if (!button) return;
  if (button.dataset.lang) { language = button.dataset.lang; localStorage.setItem('fusion-language', language); applyLanguage(); }
  if (button.dataset.view) {
    // Dragging the viewport moves the preset camera itself, so re-selecting a view restores its pose.
    setState({ view: button.dataset.view, orbit: false });
    if (renderer.ready) action('reset_camera', { view: button.dataset.view });
  }
  if (button.dataset.mode) {
    const mode = button.dataset.mode;
    setState({ mode, selected: '' });
  }
  if (button.dataset.tab) { setState({ tab: button.dataset.tab, ...(button.dataset.tab !== 'engineering' ? { playing: false } : {}) }); if (button.dataset.tab !== 'engineering') toggleAssembly(false); }
  if (button.dataset.heating) setState({ heating: Number(button.dataset.heating) });
  if (button.dataset.design) setState({ design: button.dataset.design, selected: '', playing: false });
  if (button.dataset.equilibrium) setState({ equilibrium: button.dataset.equilibrium, playing: false });
  if (button.dataset.heatScale) setState({ heatScale: button.dataset.heatScale });
  if (button.dataset.volumeStyle) setState({ volumeStyle: button.dataset.volumeStyle });
  if (button.dataset.caseDesign) setState({ design: button.dataset.caseDesign, neon: button.dataset.caseNeon === 'true', selected: '' });
  if (button.dataset.close === 'assembly-drawer') toggleAssembly(false);
  if (button.hasAttribute('data-dialog-close')) button.closest('dialog').close();
  switch (button.id) {
    case 'assembly-button': toggleAssembly(); break;
    case 'orbit-button': setState({ orbit: !state.orbit }); break;
    case 'play-button': setState({ playing: !state.playing }); break;
    case 'reset-view-button': setState({ view: 'overview', selected: '', cutaway: 80, explode: 0, opacity: 1, orbit: false, visible: Object.fromEntries((manifest.components || []).map((component) => [component.id, component.default_visible !== false])) }); await action('reset_camera', { view: 'overview' }); break;
    case 'isolate-button':
      if (!state.selected) { toast(t('selectFirst')); break; }
      setState({ visible: Object.fromEntries(manifest.components.map((component) => [component.id, component.id === state.selected])) }); break;
    case 'show-all-button': setState({ visible: Object.fromEntries(manifest.components.map((component) => [component.id, true])) }); break;
    case 'measure-button': case 'component-measure': openMeasurement(); break;
    case 'start-measure-button': await startMeasurement(); break;
    case 'clear-measure-button':
      resetMeasurement();
      if (await action('measure_clear')) renderMeasurement(); break;
    case 'provenance-button': $('#provenance-dialog').showModal(); break;
    case 'fullscreen-button': if (!document.fullscreenElement) document.documentElement.requestFullscreen?.(); else document.exitFullscreen?.(); break;
    case 'export-button':
      try {
        const exported = await api('/api/export');
        download(new Blob([JSON.stringify(exported, null, 2)], { type: 'application/json' }), `eudemo-${exported.state?.scenario || state.scenario}-${new Date().toISOString().slice(0, 19).replaceAll(':', '-')}.json`);
        toast(t('exportDone'));
      } catch { toast(t('requestFailed')); } break;
    case 'screenshot-button':
      button.disabled = true;
      try {
        const completed = await action('capture');
        if (!completed?.result?.capture_url) break;
        const response = await fetch(completed.result.capture_url);
        if (!response.ok) throw new Error('capture unavailable');
        download(await response.blob(), `eudemo-${state.design}-${state.view}.png`);
        toast(t('screenshotDone'));
      } catch { toast(t('screenshotUnavailable')); }
      finally { button.disabled = false; }
      break;
  }
});

document.addEventListener('input', (event) => {
  const element = event.target;
  if (element.dataset.state) setState({ [element.dataset.state]: Number(element.value) }, 50);
  if (element.id === 'component-search') renderComponents();
});

document.addEventListener('change', (event) => {
  const element = event.target;
  if (element.dataset.visible) setState({ visible: { ...state.visible, [element.dataset.visible]: element.checked } });
  if (element.id === 'scenario-select') setState({ scenario: element.value });
  if (element.id === 'equilibrium-select') setState({ equilibrium: element.value, playing: false });
  if (element.id === 'neon-toggle') setState({ neon: element.checked });
  if (element.id === 'line-motion-toggle') setState({ lineMotion: element.checked });
  if (element.id === 'fieldlines-toggle') setState({ fieldLines: element.checked });
  if (element.dataset.state) flushPatch();
});

document.addEventListener('keydown', (event) => {
  const row = event.target.closest('[data-component]');
  if (row && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); setState({ selected: row.dataset.component }); }
  if (event.key === 'Escape') toggleAssembly(false);
});

$('#connection').addEventListener('click', () => {
  if (patchPaused) { resumePatch(); renderConnection(); }
  if (!streamLive) { streamerStarted = false; startStream(); }
});
$('#remote-video').addEventListener('playing', () => { streamLive = true; renderConnection(); });
$('#remote-video').addEventListener('emptied', () => { streamLive = false; renderConnection(); });
for (const surface of [$('#remote-video'), $('#render-preview')]) {
  surface.addEventListener('pointerdown', (event) => { pointerStart = { x: event.clientX, y: event.clientY }; });
  surface.addEventListener('pointerup', async (event) => {
    if (!pointerStart || event.button !== 0 || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 5) { pointerStart = null; return; }
    pointerStart = null;
    const rect = surface.getBoundingClientRect();
    const sourceWidth = surface.videoWidth || surface.naturalWidth || renderer.resolution?.[0] || 2560;
    const sourceHeight = surface.videoHeight || surface.naturalHeight || renderer.resolution?.[1] || 1440;
    const aspect = sourceWidth / sourceHeight;
    const width = Math.min(rect.width, rect.height * aspect), height = width / aspect;
    const x = (event.clientX - rect.left - (rect.width - width) / 2) / width;
    const y = (event.clientY - rect.top - (rect.height - height) / 2) / height;
    if (x >= 0 && x <= 1 && y >= 0 && y <= 1) {
      await selectViewportPoint(x, y);
    }
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

