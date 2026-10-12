# EU-DEMO 聚变工程数字孪生

Windows 本机工程演示：基于 Bluemira EU-DEMO-like 概念 CAD 和源磁平衡，使用 OpenUSD、NVIDIA Omniverse RTX、Warp CUDA 与 WebRTC。提供中英文界面，不含 AI 代理。热场为标注清楚的合成降阶模型，不能用于反应堆安全或制造评定。

当前版本加入辅助加热、Ne 工况、四组设计对比、托卡马克大厅、MDL 材质、真实 RTX 视角卡片和分层双语界面。物理模型版本为 `pfc-aux-neon-budget-v3.0`，主界面在1920×1080下无需滚动；工程工具保留在独立页。

本机验收完成：Python回归150项通过、1项因Windows符号链接权限跳过，12项前端状态行为检查、41项完整浏览器检查、22项展示检查、18项可靠性检查和13项NVIDIA集成检查通过，并完成真实重启与目录迁移。整圈体场环绕约29.98 FPS，装配/体场拖动约30 FPS；20次热参数输入的实际视频响应P95为280.5 ms。版本状态、适用范围和证据见 [验证摘要](docs/validation-results.json) 与 [验收记录](docs/verification.md)。

## 启动和停止

双击 `启动数字孪生.cmd`，或在本目录执行：

```powershell
.\start-demo.ps1
```

浏览器地址为 `http://127.0.0.1:8765`。首次 Kit 启动需要等待扩展、着色器与场景加载。一个 Kit 会话使用一个浏览器串流页面。停止使用 `停止数字孪生.cmd` 或 `.\stop-demo.ps1`。

启动脚本支持 `-NoBrowser`、`-Port`、`-PythonPath` 和 `-KitPath`。运行中的服务不会因重复启动而再开一份。

`-ServerOnly` 只启动 HTTP 与计算服务，供独立验证使用。启动和停止会校验项目目录及进程身份；复制工程时不要复制 `runtime/`。同一端口已运行其他目录的服务时，启动会提示选择其他端口。同一目录已有服务或Kit时，异端口启动会被拒绝，避免共享状态被两套服务覆盖。

## 运行环境

本机已配置独立 Kit 110.1.3 运行时，扩展文件已实体复制，不依赖原项目的 `_build` 目录或链接。Python 和 Kit 路径由忽略版本控制的 `runtime.local.json` 管理，示例见 `runtime.example.json`。

解析优先级为启动参数、环境变量、本地配置；Python 最后尝试 `.venv/Scripts/python.exe`。环境变量为 `FUSION_PYTHON`、`FUSION_KIT_EXE`、`FUSION_EXT_FOLDERS`（分号分隔）。Python 版本和依赖见 `pyproject.toml`。Kit、CUDA 兼容显卡和对应 NVIDIA 扩展需单独准备，保留其许可。

需要从已有安装提取独立运行时时，可用 `tools/import_runtime.py --source-build <安装目录> --destination <新的独立目录>`。该工具复制现有安装并实体化链接，不下载扩展，也不覆盖已有目标目录。

源资产已经保存在本项目。日常演示无需启动 WSL2；重新生成 Bluemira CAD 时可以使用既有 WSL2 环境。

## 演示功能

- 两种设计：常规偏滤器与 LongLeg；各有 reference、rampup、sof、eof、rampdown 源磁平衡快照。
- 装配树、隐藏/隔离、部件尺寸、两点测量、世界角度剖切、装配爆炸、透明度、环绕及五个观察视角。
- 温度、线性/对数热流、按源场强着色的三维磁力线、等离子体截面，以及同一几何和平衡下相对 Ne 关闭基准的温度/热流差值场。
- 20、35、50、65 MW 辅助加热与 Ne 开关；常规/LongLeg × Ne 关闭/开启四工况共用控制参数和热流色标。
- 额定、低负荷、低冷却流量、高热负荷工况；准稳态负荷扫描与功率收支、未解析功率显示。Ne 开关展示假设辐射增强与热流展宽的效果。
- 等离子体体积场入口在 RTWT/Kit-CAE 后端就绪后启用，使用 NanoVDB、IndeX 与 RTX Real-Time 2.0 深度合成。
- 带数据来源的工况 JSON、完成确认后的原生 RTX PNG、源扇区 STEP 和双设计 USD 场景导出。

全机包含 11 个系统、1,458 个逻辑部件实例。PF/CS/等离子体使用源截面回转表面，内部径向端盖不参与全环显示；剖切和爆炸时只显示需要的外露端盖。源辐射屏蔽是 20°扇区，保留 18 份实例。显示网格与受热分析网格分别组织。

## 数据与物理边界

`assets/source/eudemo/` 保留 STEP、命名网格、机器参数和源磁平衡。`assets/source/provenance.json` 记录上游提交、许可、生成方式和源文件 SHA-256。几何使用 mock PROCESS 径向输入，磁平衡含本地生成约束，属于概念设计。

源参数 `P_fus=1994.6` 的 `W` 标签存在已知单位问题。应用不使用该标签作为功率输入；工程高级参数 `power` 表示不含辅助加热的基准热功率预算，默认2000 MW。辅助加热 `heating` 默认50 MW，假设全部被装置吸收；默认满负荷总预算为2050 MW。负荷扫描按同一无量纲比例缩放基准预算和辅助加热。

热场在面向等离子体的表面归一化，并与简化体积热源合成同一功率账本。基准预算的80%分配到包层体积热源，其余20%与辅助加热进入等离子体通道，再分配为核心辐射、SOL辐射、壁面与靶板粒子功率。各通道不重复计数；出口温度使用实际吸收功率，未解析功率单列。

Ne 是没有注入速率单位的布尔假设，改变 SOL 辐射比例和合成热流展宽；模型不求解杂质输运或脱靶，不能据此宣称实测脱靶或 LongLeg 在所有平衡下都优于常规设计。四工况共享总预算、分离面功率与冷却参数。差值基准保留当前设计、平衡及其他控制参数，只关闭 Ne。

所有工况共享热流线性色标0–200 MW/m²和对数色标0.01–200 MW/m²，使用 inferno 顺序色带；零值/无数据单独显示，超范围数量随数据导出。磁力线采用轴对称源场和 `Bphi=fvac/R`，颜色对应轨迹处的源场强。负荷扫描没有秒单位；模型没有 TF 纹波、三维遮挡、传感器遥测和经验证的瞬态输运。

完整模型说明见 [物理模型](docs/physics-model.md)。80组可复现预制工况位于 `assets/scenarios/manifest.json`，覆盖2种设计×4档加热×2种Ne状态×5个源平衡，均为满负荷扫描位置。预制包的数值检查不等于真实装置物理验证。USD 默认设计为 conventional，并保留 longleg 变体；CAD ZIP 保留原始扇区 B-rep 语义。

## 架构与开发

- `app/fusion_twin/`：状态校验、命令队列、字段版本、功率账本、Warp 计算和缓存回收。
- `web/`：双语界面及官方 NVIDIA WebRTC SDK 封装。
- `kit/`：工程控制器、RTWT schema/workflow 和 Kit-CAE 体场适配器。
- `assets/`：原始来源、可重建场景、预制工况和下载包。
- `tools/qa/`：真实浏览器、恢复、画质和性能验收。
- `runtime/`：本机日志、状态、缓存和截图，不入版本控制。

NVIDIA 控制链路由 `kit/workflow/workflow.toml` 声明20个控制项。官方 WebRTC 数据通道中的标准 RTWT `set_state` 写入 USD AppState，USD 变更通知将请求交给异步 worker，再进入同一状态校验与计算协调器。界面的 REST 和 RTWT 两个入口共用该协调器；非法参数会报告错误并回滚 USD，连续写入保留最后请求。workflow 的 Variant、Attribute 和 Callback 只负责声明式绑定，Callback 不承担求解或缓存发布；计算和体场处理由异步 worker 推进。

数据链路为：参数校验 → 根据模型版本、设计拓扑、源平衡与物理参数生成字段键 → 命中缓存或计算 → 发布 `runtime/fields/<key>.npz` 不可变快照 → Kit-CAE SimData / NanoVDB → RTWT `publish_results` 与 `GetField` 回读 → IndeX 原生体渲染。体缓存另包含体网格模型版本和剖切角度，记录命中、失效和发布完成；`applied_volume_field_key` 只在对应 IndeX GPU 结果就绪后更新。该项目使用真实 RTWT 控制、消息、结果发布和 Kit-CAE 算子，同时保留本项目的计算协调器；它是针对聚变演示定制的 NVIDIA 组件集成，不是上游流体蓝图的完整原样部署。当前流程采用数值生成的合成场与 Warp CUDA，不包含 AI 代理、神经网络推理或 Triton 服务。

等离子体体场由已提交的合成 R–Z 温度剖面轴对称回转、插值到 **128×128×112** 网格，体素间距为 **0.21875×0.21875×0.15 m**。剖面形状参考源磁平衡，温度幅值随规定的热功率、负荷和 Ne 假设变化，属于合成演示数据。粉紫等离子体样式用于空间形态展示；科学温度样式使用固定 **0–40 keV** 色标。两种样式共享同一温度字段，仅修改颜色与透明度传递函数；实际数据最小/最大值单独报告，不改变色标范围。

展示大厅位于独立的 `/World/Environment` 层级，由 `tools/build_scene.py` 自建混凝土坑墙、平台、吊车和尺度参照，不计入源工程 CAD 部件。材质使用本机 NVIDIA MDL `OmniPBR`，项目生成的 `FusionPBR.mdl` 提供参数封装；混凝土和拉丝金属法线贴图由固定随机种子的数值程序生成，无外来贴图。纹理采用以米为单位的世界投影。环绕时根据相机位置与墙段范围隐藏遮挡主机的近侧大厅墙及关联立柱，背侧背景保留；规则仅作用于 `/World/Environment/Hall`，不改动工程 CAD 的显示状态、测量或源几何。

协议见 [data-contract.md](docs/data-contract.md)。命令具有请求 ID、会话和执行完成确认；字段快照引用带内嵌身份的不可变 NPZ。Kit 更新发生在 USD 会话层。开发时修改控制器后需要重启 Kit，避免自动热重载混用协议模块。

大型生成资产使用本机已有的 Git LFS：`.gitattributes` 跟踪生成场景 USDC、预制字段 NPZ、下载 ZIP 和界面 PNG。此次配置未改写 Git 历史，已有历史对象仍保留，因此旧仓库体积不会随之缩小；新机器检出这些资产需准备 Git LFS。

QA 文件可手动归档：`python tools/archive_qa.py <相对目录>` 只统计 `runtime/qa` 下指定子目录的 PNG 和总占用；显式使用 `--archive <相对目录>` 才创建 `runtime/qa/archives/` 内的新 ZIP。工具保留完整目录文件和 SHA-256 清单，重新读取校验成功后，只移除已打包且未变化的源文件，保留源目录。它拒绝越界路径、链接和已有同名归档，不修改旧报告内容，也不自动周期运行。

```powershell
. .\tools\runtime.ps1
$fusionRuntime = Resolve-FusionRuntime -ProjectRoot $PWD
$env:PYTHONPATH = Join-Path $PWD 'app'
& $fusionRuntime.Python -m unittest discover -s tests -v
npm ci
npm ci --prefix tools/qa
npm run check:web
npm run build:streamer
node tools/qa/reliability.mjs
```

真实重启验收会重启本项目进程，须与浏览器测试串行执行：

```powershell
& $fusionRuntime.Python tools/qa/restart_reliability.py --execute
node tools/qa/nvidia.mjs
node tools/qa/performance.mjs
```

迁移检查使用新建的英文临时目录（包含空格）与 8766 端口，保留副本及日志，并退出自己启动的进程：

```powershell
& $fusionRuntime.Python tools/qa/portability.py --execute
# 主 Kit 已停止、GPU 测试窗口空闲后，再验证迁移副本的 Kit 与原生截图：
& $fusionRuntime.Python tools/qa/portability.py --execute --with-kit
```

上述检查复用已配置的 Python/Kit 运行时，验证工程目录可移动；新机器仍需安装对应运行环境并填写 `runtime.local.json`。

场景更新先用 `tools/build_scene.py --output-assets <候选目录>` 生成候选，再使用 `tools/publish_geometry.py` 原子发布；运行中的 USD 文件可能被映射，不能直接覆盖。构建默认复用已交付的 `assets/source/`。只有显式传入 `--source-project <来源工程>` 才会导入并更新源资产；`--skip-copy` 保留兼容，始终跳过导入。导入时可选 `--provenance-root <来源仓库父目录>`，从其中的 `bluemira/` 和 `eudemo/` 复制许可与生成配置；目录可为本机路径或显式 WSL UNC 路径，没有预设发行版和用户名。`tools/bake_scenarios.py --output <候选目录> --device cpu` 生成独立预制包；生成器禁止指向实时 `runtime` 和已发布的 `assets/scenarios`，候选验证完成后再单独发布。

## 图像质量

WebRTC 输出固定 2560×1440（QHD）、目标 30 FPS，关闭帧生成。相机运动、环绕或负荷播放期间，内部视口使用 1920×1080；相机停稳 0.75 秒且停止环绕/播放后，恢复原生 2560×1440 视口尺寸。PNG 直接从当前 RTX 视口捕获，并请求完整 QHD 细节。运动期间的 QHD 串流来自 1080p 视口，不能称为原生 QHD 运动渲染。

装配、磁力线、温度、热流、两种差值、等离子体截面和体积场的实时画面与 PNG 统一使用 RTX Real-Time 2.0（`RealTimePathTracing`）。运动、停稳和截图均保持同一渲染引擎，质量切换只调整视口分辨率。

RT2 使用 DLSS Quality（`execMode=2`）时间重建；其视口尺寸不等于逐像素原生采样，也不使用静止积累 256 样本的离线路径追踪策略。体积场另使用 IndeX 稳定深度合成（`compositeDepthMode=3`），已做同相机、同字段的 CAD 遮挡对照。

温度、热流、差值和截面的纯字段更新在下一帧后请求 DLSS `forceParamReset`，结构/模式切换等待 3 帧后请求同一重置，清除旧画面的重建历史。连续数值输入复用待执行任务，完成时记录最新状态版本和字段键；已有结构/模式切换任务不会被字段更新反复取消。

验收分别测量接收、解码和实际呈现帧率，并检查固定左右包层及全可见热场的低→高→低颜色回归。Kit 心跳 FPS 和静止视频30 FPS均不能证明旋转流畅。上一版已通过装配/体场环绕、拖动、完整功能流程和20次实际像素响应检查；新版字段、界面及渲染更新仍需完整复测。历史性能数值适用于本机RTX 5070 Ti与单个可见Edge串流会话。

## 来源

- [Bluemira EU-DEMO](https://github.com/Fusion-Power-Plant-Framework/bluemira-eudemo)
- [Bluemira](https://github.com/Fusion-Power-Plant-Framework/bluemira)
- [NVIDIA Digital Twins for Fluid Simulation](https://github.com/NVIDIA-Omniverse-blueprints/digital-twins-for-fluid-simulation)

上游版权与许可保留在 `assets/source/provenance/` 和 `web/vendor/`。技术名称只用于注明实际采用和完成验证的能力。
