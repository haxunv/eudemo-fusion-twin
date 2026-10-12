# 验收记录

## 当前展示升级版（2026-10-12，本机验收完成）

本节对应 `pfc-aux-neon-budget-v3.0`：辅助加热、Ne 合成情景、四工况对比、托卡马克大厅、MDL 表面、按源场强着色的磁力线、128×128×112 NanoVDB 和新版双语界面。硬件为 Windows / RTX 5070 Ti 16 GB / Kit 110.1.3；浏览器性能检查使用可见 Edge、默认 GPU 合成。完整数值、代码和证据 SHA-256 见 [validation-results.json](validation-results.json)。

| 范围 | 本轮实测结果 | 证据（项目内路径） |
| --- | --- | --- |
| Python / CUDA 回归 | 151项执行：150通过、1跳过，24.097秒；包含80组CPU/CUDA热场对照、10组磁场对照、496个独立表面历史样本及体场A→B→A竞争回归 | `runtime/qa/unit-v3-release.txt` |
| 前端状态行为 | 12项通过：设计/平衡变化、过期异步测量、比较卡焦点和相机辅助状态；新增Python入口另行执行通过 | `web-ui-state-v3.txt`、`web-ui-wrapper-v3.txt` |
| 80组预制工况 | 覆盖2设计×4加热×2Ne×5源平衡，2480个历史点；独立面积积分、字段身份、功率账本和冷却KPI一致，账本最大残差2.38×10⁻¹³ MW | 全套Python日志、`assets/scenarios/manifest.json` |
| 双语展示 | 22项通过：中英文主界面与对比页1080p无滚动、主要文字≥12px、7张原生RTX图片来源/哈希、固定色标、四工况与平衡快照 | `runtime/qa/showcase.json` |
| 完整交互流程 | 41项通过；全流程29.95 FPS、0掉帧，稳态30.10 FPS；包含切模式、剖切、隐藏、爆炸、真实PNG和完整CAD/USD导出，无JS错误 | `runtime/qa/acceptance-v3-final.json` |
| 针对性界面回归 | 5项通过：设计和平衡切换退出测量、下一次点击恢复选择、相机aria状态、对比卡跨轮询/结果更新保焦并可按Enter选中 | `runtime/qa/ui-regression.json` |
| 命令与字段可靠性 | 18项通过：100个连续动作、去重、10组设计/平衡、快速滑动、慢响应/失败恢复及导出一致性 | `runtime/qa/reliability.json` |
| NVIDIA 集成 | 13项通过：20个真实RTWT控制项、标准set_state求解、非法参数回滚、最后请求保留、NanoVDB精确回读、固定温度色标和3轮隐藏体场后更新再显示 | `runtime/qa/nvidia.json` |
| 装配/体场运动 | 装配环绕29.92、拖动29.90 FPS；体场环绕29.99、拖动29.94 FPS，均0掉帧 | `runtime/qa/performance-v3-assembly.json`、`performance-v3-volume.json` |
| 完整大厅环绕 | 体场＋磁线动画连续66秒，29.98 FPS、0掉帧；3段近侧遮挡墙正确隐藏/恢复，CAD可见性与场身份保持一致；统计含截图时段 | `runtime/qa/hall-orbit-v3-release.json` |
| 像素响应 | 20次完整DOM输入→视频变化，P50 278.0、P95 280.5、最大280.7 ms；固定双包层区域和完整可见热场共同达标 | `runtime/qa/latency-v3-release.json` |
| 真实重启 | 确认丢失恢复、Kit重启取消旧会话动作、服务重启保留完成结果与截图哈希三项通过 | `runtime/qa/restart-reliability.json` |
| 目录迁移 | 新英文带空格目录、8766端口，9项通过；双设计、MDL场景、20个RTWT控制、原生QHD与IndeX均正常；测试进程3.672秒退出 | `runtime/qa/portability-kit.json` |
| 测量和来源 | 两次实际模型表面点击，7.4034 m，与世界坐标独立计算一致；JSON完整来源和字段身份匹配 | `runtime/qa/measurement.json` |

Python跳过项仅为普通Windows符号链接创建权限不可用；目录联接拒绝检查已经通过。前端语法、串流构建和Git空白检查通过。源CAD、平衡及来源资产没有改动；生成二进制由已有Git LFS管理，不改写历史。QA归档工具已通过测试，本轮没有删除或归档已有验收材料。

输出视频和静止原生PNG为2560×1440，运动内部渲染为1920×1080；始终采用RTX Real-Time 2.0，景深关闭。磁线本体保持缓存，只更新小规模方向标记；方向动画不表示粒子速度。热史由逐点表面重复求解改为同一热阻定律的分区极值批量计算，完整计算从37次kernel/同步降到7次，GPU独立样本回归通过。修改前像素P95为313.4 ms，保留于 `latency-v3-framing.json`；最终测试没有缩小取样区域或放宽300 ms门槛。

最后修复了两个体场时序窗口：CAE隐藏算子不执行时，先完成显示绑定再发布新字段；已显示A、发布B途中返回A时，先取消旧字段的直接复用资格，完整事件/GPU确认后再标记应用。CPU测试精确注入后一窗口和发布失败，恢复旧逻辑时能检出错误；随后真实NVIDIA、重启及迁移测试通过。运动/延迟证据记录于最后这项发布竞争修复之前，相关渲染参数和热求解实现未再变更。最终测量/焦点修复后又执行了5项真实UI回归、测距和41项完整流程。

默认展示已恢复为中文、常规偏滤器、平顶开始、50 MW辅助加热、Ne关闭，磁力线与粉紫体场开启。可查看 `runtime/qa/delivery-v3-zh.png` 和 `delivery-v3-native.png`。粉紫色只展示空间形态，科学温度样式对应固定0–40 keV合成场；Ne只表示规定的辐射/展宽假设，无杂质输运或脱靶验证。该版本使用真实RTWT/Kit-CAE/NanoVDB/IndeX/Warp组件，同时保留项目计算协调器，不含AI代理或Triton推理。

以下历史记录按当时版本保留。部分固定文件名的QA报告已被新运行更新；历史数值不能替代本节结果，旧哈希只代表当时记录。

## 历史：工程修复版（2026-10-12）

本节覆盖 `75e51cf` 之后的工程优化。机器可读摘要及代码、证据文件SHA-256保存在 [validation-results.json](validation-results.json)。后面的首版记录保留为历史证据，不代表当前版本仍有相同缺陷，也不能代替当前版本的回归。热场是 `synthetic_demo`，数值自洽检查不等于真实装置物理验证。

| 范围 | 已获得的证据 | 尚需关闭的内容 |
| --- | --- | --- |
| 命令与字段协议 | `runtime/qa/reliability.json` **18 项通过**：100个并发动作、重试去重、10组设计/平衡、差值场、导出一致性、持续滑动，以及慢响应/临时失败/恢复/参数拒绝 | 本项通过；旧503失败记录保留在 `reliability-final.log` |
| 真实重启恢复 | `runtime/qa/restart-reliability.json` 三阶段通过：确认丢失恢复、Kit 重启取消旧动作、服务重启保留已完成结果与截图哈希 | 不宣称任意崩溃窗口下严格 exactly-once |
| Python 回归 | `runtime/unit-tests.log` **108 项通过**，耗时17.968秒，包含启动身份、同目录异端口拒绝、预制数据、全模式RT2、连续字段重置及状态文件读取竞争检查 | 本项通过 |
| 预制数据交付 | `tests/test_baked_scenarios.py` 已纳入上述整套测试；逐一读取 40 个交付字段包，核对版本、独立三角面积分、功率账本和冷却 KPI | 本项通过；保留合成模型适用边界 |
| RTWT / Kit-CAE / IndeX | `runtime/qa/nvidia.json` **7项通过**：真实WebRTC控制清单、UI写入、原生NanoVDB、缓存命中及剖切失效、双设计切换、装配运动与停稳均RT2、消息请求全部确认。`runtime/depth-probe/analysis.json` 与迁移原生截图确认RT2＋深度模式3的CAD遮挡 | 本项通过；报告附代码哈希 |
| 集成性能 | `performance-release-assembly.json`：环绕 29.97 FPS、拖动 29.96 FPS；`performance-release-volume.json`：环绕 30.13 FPS、拖动 29.95 FPS。两者均为真实可见 Edge 浏览器，运动/拖动均 0 掉帧 | ≥24 FPS、掉帧率≤5%通过；记录每阶段实际引擎和代码哈希 |
| 完整功能流程 | `acceptance-release-complete.json` **36项通过**：全流程30.00 FPS、0掉帧，稳态30.09 FPS，JS/资源错误为空；CAD/USD完整下载字节与交付文件相同 | 本项通过；保留截图版35项独立证据 |
| 路径与启动 | `runtime/qa/portability-kit.json` **9 项通过**：英文带空格目录、8766 端口、双设计计算、跨项目端口/PID 防误操作、真实 Kit/RTWT/IndeX 与原生 QHD 截图；运行时目录链接数为零，测试进程退出耗时 3.578 秒 | 同机目录迁移通过；新机器仍需配置 Python、Kit 和驱动 |
| 热参数端到端响应 | `runtime/qa/latency-release-rt2.json`：20次真实 DOM→RTWT→视频采样，响应中位数254.8 ms、P95 280.5 ms、最大280.8 ms；读回P95 13.9 ms，HTTP观察P95 6.0 ms | 300 ms目标通过；不以服务确认或Kit字段版本替代像素变化 |
| 测量与来源导出 | `runtime/qa/measurement.json`：实际CAD表面两次点选，距离8.5024 m，与三维点坐标独立计算一致；JSON来源及字段身份一致 | 本项通过 |

默认CPU几何重建只传 `--output-assets`，1.781秒完成；两设计各11系统、1458逻辑部件、2682网格、1,418,328三角形与交付manifest一致，USD没有未解析引用。212个源资产及来源文件SHA-256全部保持不变。新默认不读取旧项目路径，不发布临时候选目录。前端语法检查、串流构建及Git差异空白检查也通过。

性能数值使用浏览器 `requestVideoFrameCallback` 的实际呈现计数。输出视频和静止截图为 2560×1440；运动时内部渲染为 1920×1080。静止约 30 FPS、收到 30 FPS 或 Kit 心跳约 30 FPS 均不能替代持续运动呈现验收。

所有模式、运动、停稳和原生PNG统一采用 `RealTimePathTracing`（RTX Real-Time 2.0），DLSS Quality；体场另使用 `rtx.index.compositeDepthMode=3`。本机 Kit 110.1.3 的路径追踪体场对照出现中央螺线管穿透，不能仅开启深度选项就宣称修复。RT2 深度模式 3 在相机偏移 0 与 2.8 的对照中遮挡正确；迁移副本的 `relocated-volume.png` 和 `relocated-assembly-restored.png` 已目视核对，并验证当前体场字段身份、NanoVDB 精确往返、15 个 RTWT 控制项和实际渲染模式。截图路径及 SHA-256 保存在 `portability-kit.json`。

停稳后恢复离线路径追踪的中间方案虽然通过环绕/拖动检查，却在完整功能流程中仅有10.26 FPS（自动截图）和11.85 FPS（关闭自动截图）。隐藏、爆炸和磁力线切换之后的800 ms窗口仅约1–4 FPS。当前统一RT2后，`acceptance-rt2-workflow.json` **36项通过**，全流程30.04 FPS、0掉帧；统计包含所有操作和原生PNG导出，未排除重建区间。`acceptance-release-visual.json`截图版 **35项通过**，全流程29.99 FPS，浏览器错误为空。自动页面截图本身可能影响呈现，故性能硬门槛使用不自动截页面、仍保留原生PNG导出的流程。

`acceptance-release-rt2.json`保留一次失败：全部功能及帧率已通过，但浏览器出现 `ERR_NO_BUFFER_SPACE`。Windows System / Tcpip事件4231（RecordId 139798，2026-10-12 07:42:55.598）确认同一时刻全局临时TCP端口分配失败。后续8765无挂起连接，未发现本项目连接泄漏证据；增加失败URL诊断后的上述截图回归通过。未修改生产HTTP策略或忽略浏览器错误来通过检查。

首轮 `latency-current.json` 仅完成17次，GPU→CPU读回阻塞到秒级；该失败记录保留，不作为当前通过证据。随后确认原生RTX也存在热场旧颜色残留，CPU字段和USD颜色正确。科学模式改为RT2/DLSS Quality后，在字段应用下一帧设置一次 `/rtx-transient/post/dlss/forceParamReset`，由渲染器消费并自动清零。`field-dlss-oneframe` 原生低→高→低截图的左右受热面回归误差分别为0.37和0.45/255。

最终像素校准使用固定左右包层各1100像素，以及只按初始低温图锁定的完整可见热场；不再剔除响应失败或未回归区域。三个区域各自检查信号、噪声、至少90%响应覆盖和95%回归覆盖；试验要求三个区域共同达到响应阈值。20次输入均完整确认服务、字段及像素；两次预热单列，不计入统计。阈值定义及完整逐帧数据保存在 `tools/qa/latency.mjs` 和上述JSON，测试表示此机器、此工况下的浏览器视频响应，不等同物理显示器光电测量。

DLSS重置语义参考 [NVIDIA官方说明](https://docs.isaacsim.omniverse.nvidia.com/latest/replicator_tutorials/tutorial_replicator_sdg_workflows.html#dlss-temporal-reset)。实际复位消费、原生截图与浏览器像素结果均在本机验证，不能仅凭设置存在判断生效。

### 对旧版评审数值的复核

独立复现旧版公式与源 CAD 三角形得到总实体表面积 13,021.2763 m²；名义 2000 MW 时，扫描两端表面热流积分分别为 2,628.2217 MW 和 11,937.9651 MW，出口温度保持 409.8901°C。该面积包含背面/内部面，不能作为有效等离子体受热面积。当前实现使用独立 PFC 表面和统一功率账本，见 `physics-model.md`。

两设计的辐射屏蔽源主体都为 20° 扇区。直接对旋转轴附近 R≈3×10⁻¹⁶ m 的四个点计算 atan2 会产生 90°；排除这些点后角域严格为 0–20°，源文件 SHA-256 与基线相同。因此没有把辐射屏蔽改为单份。源等离子体的 502 个径向端盖三角形、PF/CS 集合的 396 个径向端盖三角形则确实存在；当前回转表面与外露端盖分开管理，并有整环、剖切和爆炸检查。

---

## 历史：首版验收

日期：2026-10-11。设备：Windows、RTX 5070 Ti 16 GB。

## 首次720p验收

| 检查 | 结果 |
| --- | --- |
| Python 自动测试 | 25 项通过，含 CUDA/CPU 数值一致性与 Windows 文件锁恢复 |
| 完整浏览器交互 | 32 项通过，JavaScript 错误 0 |
| 显示交互回归 | 8 项通过，直接检查解码视频像素变化 |
| 路径追踪视频 | 1280×720，平均接收 29.95 FPS，未启用帧生成 |
| 两点测量 | 通过浏览器点击 CAD 表面，结果 8.5023 m |
| 导出 | JSON 完整来源、实际 RTX PNG、CAD ZIP、USD ZIP |
| 前端 | 语法检查、串流构建通过；npm audit 0 漏洞 |
| 启动 | 正式配置冷启动、运行中重复启动通过 |

浏览器为本机 Microsoft Edge，自动化使用单个独立会话。温度→磁力线切换时，核心区域解码视频平均像素差为9.58（0–255通道值），并完成截图目视检查。

## 复现与证据

- `tests/`：几何、场数据、状态和导出测试。
- `tools/qa/acceptance.mjs`：完整交互验收。
- `tools/qa/presentation.mjs`：模式切换及实际图像变化。
- `tools/qa/measurement.mjs`：实际点击测距及导出来源。
- `runtime/qa/acceptance.json`、`presentation.json`、`measurement.json`：本次运行结果。
- `runtime/qa/10-temperature-clean.png`、`11-magnetic-clean.png`、`13-measurement.png`、`14-delivery.png`：最终截图。

## 使用边界

CAD 与平衡文件由本地 Bluemira / EU-DEMO 开源框架生成，径向构型使用 mock PROCESS 输入，平衡含自定义约束；它们属于概念设计资产，未经官方 EU-DEMO 运行验证。热场为这些概念 CAD 上的可复现演示计算，假设与来源随 JSON 一起导出。当前无装置遥测，也无 AI 代理。CAD 下载包含源扇区 STEP；完整环形装配采用 OpenUSD。来源见 `assets/source/provenance.json`。

## 1440p清晰度修正（历史配置）

原生渲染、窗口帧缓冲、WebRTC协商统一为2560×1440，像素数是原720p的4倍。视窗关闭自动跟随UI尺寸，防止纹理被重新设为低分辨率。SDK读取实际渲染分辨率，截图、拾取和测量保留正确的原生尺寸。路径追踪改为每帧2个样本、静止最多积累256个样本，保留OptiX降噪。

- `tools/qa/clarity.mjs`：原生PNG和浏览器解码视频均为2560×1440，页面JavaScript错误0。
- 最终Headless Edge软件合成测试：静止29.83 FPS、环绕呈现28.61 FPS，4秒运动统计段丢帧1帧。这是特定测试配置的结果，并非所有浏览器的性能保证。
- 默认GPU合成的Headless Edge在环绕时出现约1 FPS；移除面板模糊未改善。相同Kit配置、浏览器关闭GPU合成后恢复约29 FPS。2026-10-12用户已确认普通可见浏览器旋转也明显卡顿，后续修正与验证见下文。
- 1440p浏览器双点测量回归通过，距离8.5023 m；JSON导出来源保留。
- 前端语法检查、SDK打包、桥接Python语法检查通过；本次未重复与画质无关的数值测试。

证据：`runtime/qa/clarity.json`、`clarity-headless-gpu.json`、`clarity-native-1440p.png`、`clarity-stream-1440p.png`。软件合成复现：在项目根目录设置`$env:QA_SOFTWARE_BROWSER='1'`后运行`node tools/qa/clarity.mjs`。

项目复用本机 `D:/nvcode` 的 Python 与 Kit 安装。日常运行无需 WSL；移至新机器时需配置对应环境。

## 2026-10-12 评审核验

以下为本轮代码、资产和运行证据核验。上述历史通过记录保留；静止或整段视频平均约30 FPS不能证明持续旋转流畅。原720p交互验收没有独立的持续运动呈现帧率门槛，本轮增加该门槛。

### 自适应渲染修正

保持WebRTC输出2560×1440；运动时内部渲染1920×1080，再输出1440p视频；停下0.75秒后内部渲染恢复2560×1440。路径追踪每帧1个样本，静止最多积累256个样本。运动图像不能称为原生1440p渲染。

| 默认GPU浏览器测试 | 修正前：原生1440p、2 spp | 最终回归：自适应、1 spp |
| --- | --- | --- |
| 环绕呈现帧率 | 1.496 FPS | 29.916 FPS |
| 环绕接收帧率 | 28.928 FPS | 29.916 FPS |
| 环绕解码帧率 | — | 29.916 FPS |
| 环绕统计窗口与丢帧 | — | 6.0169秒，0帧 |
| 手动拖动呈现帧率 | — | 29.893 FPS |
| 手动拖动统计窗口与丢帧 | — | 4.1147秒，0帧 |
| 静止呈现帧率 | — | 29.863 FPS |

`tools/qa/performance.mjs`在默认GPU合成的自动化浏览器中通过环绕和手动拖动呈现至少24 FPS硬断言。运动及拖动内部1920×1080、拖动`quality=interaction`、静止恢复内部2560×1440、原生PNG截图2560×1440的断言均通过。证据为 `runtime/qa/performance-qhd-2spp-baseline.json` 与 `runtime/qa/performance-adaptive-final.json`。

本轮 `tools/qa/measurement.mjs`双点测量回归通过，距离8.5023 m，JSON导出provenance检查通过；证据为 `runtime/qa/measurement.json`。`npm run check:web`、`npm run build:streamer`、Python `py_compile`检查通过，`start-demo.ps1 -NoBrowser`运行中重复启动通过。本轮未重跑历史25项物理/状态测试。

修正前接收帧率接近30而呈现仅约1.5 FPS，结合软件合成对照和用户反馈，支持浏览器与Kit争用GPU资源的判断。单独使用接收帧数或`gpu_ms`都不足以说明用户实际看到的流畅度。以下计算与发布链问题仍需单独整改，不能仅靠降低渲染负载覆盖。

### P1：交互与状态一致性

| 核验项 | 当前事实与影响 | 证据与待整改 |
| --- | --- | --- |
| 服务锁内完整计算 | 状态更新持有同一锁完成计算和发布；每次热参数变化执行当前工况、基准和31步历史，共33次同步求解，阻塞同期读取与动作。播放每0.5秒再次更新。纯相机环绕在Kit内进行，不会每帧触发这条求解链。 | `app/fusion_twin/server.py` 的 `snapshot`、`patch`、`_playback`；`compute.py` 的 `_solve`、`compute`。应缩短锁范围，复用历史/基准，测量参数输入到图像呈现的完整延迟。 |
| 字段发布与USD重复更新 | 热变化写完整NPZ，包含未变化的几何和磁线；Kit状态应用会遍历材质并调用字段更新，文件时间变化分支还可再次更新。科学场拓扑已有缓存，不能称为每次全部重建。 | `compute.py:223`；`kit/extensions/fusion.twin.bridge/fusion/twin/bridge/extension.py` 的 `_poll`、`_apply_state`、`_apply_materials`、`_apply_fields`。应按变化范围更新，避免重复文件加载、材质绑定和静态数组上传。 |
| 动作实际为单槽覆盖 | 返回值虽写`queued: true`，服务只保存最新`command`与序号；Kit轮询间隔内多个动作可被覆盖，快速拾取/测量不能保证逐个执行。 | `app/fusion_twin/server.py:136` 与桥接 `_poll`。需动作队列或明确的逐项确认机制，并验证快速连续点击。 |
| 多文件版本未校验 | `fields.npz`、`fields.json`、`state.json`分别原子替换；Kit分别读取，未核对字段与状态的revision，存在跨版本组合窗口。仅比较数值相等也不足以修复：纯视图变化会增加状态revision但复用字段。 | `compute.py:229`、`server.py` 的 `_publish`、桥接 `_apply_fields`。需独立的字段版本标识、匹配读取及已应用版本确认。 |

前端150ms滑块防抖与单个在途请求会合并尚未发送的状态；不存在无限增长的前端更新队列。状态轮询为前台1秒、后台2.5秒；每2秒PNG回退只在实时串流未连接时工作，不能直接解释正常串流的旋转卡顿。证据：`web/app.js` 的 `setState`、`flushPatch`、`poll`、`updatePreview`。应区分服务锁等待、Kit重复更新和GPU呈现瓶颈。

### 物理与几何边界

| 核验项 | 结论 |
| --- | --- |
| 热流与时间响应 | 当前为固定空间高斯热点及单调升温响应，没有strike-point跟踪或Eich热流模型。热流未按全堆热功率守恒归一，冷却回路使用独立假定能量平衡。`app/fusion_twin/compute.py`。 |
| 已有但未接入的能力 | 源数据含阶段平衡与LongLeg变体；旧项目已有 `D:/nvcode/fusion-twin/tools/fusion/fusion_bake/heatload.py`。当前页面阶段和热参数没有驱动这些平衡/热流模型，不能把这些资产的存在视为已实现功能。`assets/source/eudemo/`、`compute.py`。 |
| 磁力线 | 在轴对称磁场中进行三维轨迹积分，采用`Bφ=fvac/R`近似；结果是三维曲线。当前固定参考平衡，不随热参数变化。`compute.py` 的磁线积分与初始化。 |
| 热网格规模 | 当前热计算使用5542个源网格顶点；CAD三角面数量不等于热求解自由度。`compute.py` 的 `field_samples` 与源网格载入。 |
| 扇区规范化 | PF、CS和plasma源扇区进行了22°→20°角度变换，属于几何规范化，应保留在来源说明中。`tools/build_scene.py:223`。 |
| CS识别 | 当前按源部件最大半径小于3.8 m从PF中识别CS；本批资产核验未发现误分类，后续来源变化需重新验证。`tools/build_scene.py:237`。 |
| TF剖切 | 同号TF扇区与其他部件剖切边界存在10°偏移，需校正剖切选择或统一扇区定义；核验不支持“全机装配错误”的结论。`tools/build_scene.py` 的装配变换与桥接 `_apply_state`。 |

### 架构差距与P2移植、交付问题

| 核验项 | 当前事实与待整改 |
| --- | --- |
| 上游架构接入 | 当前采用独立HTTP服务、Warp计算、自定义USD桥接和NVIDIA WebRTC SDK，未接入RTWT、KitCAE、OmniSci，也没有上游cache-key工况缓存协议；仅有当前输入的`last_signature`复用。需要在后续工程计划中明确保留或接入方案。首版无AI与采用RTWT Lite并不冲突；未展示体场时，NanoVDB/IndeX不构成必需组件。证据：`app/fusion_twin/`、`kit/apps/fusion_twin.kit`、`web/streamer/index.js`。 |
| 本机路径依赖 | Kit可执行文件及扩展缓存仍写死在`D:/nvcode`；启动Python路径可覆盖，场景构建也支持`--source-project`和使用已有资产，不能统称所有构建均无法移植。需集中配置环境路径并做新路径启动验证。`tools/launch_kit.ps1`、`kit/apps/fusion_twin.kit`、`start-demo.ps1`、`tools/build_scene.py`。 |
| Git交付基线 | 本轮核验时Git无提交、无已跟踪文件，296个非忽略未跟踪项。需形成可重现的版本基线后再交付源码；此处只记录状态，不执行提交。 |
| 目录体积 | 核验时工作目录143.90 MiB，其中资产51.97 MiB、runtime 37.30 MiB、根node_modules 35.85 MiB；runtime和依赖已被`.gitignore`忽略。约9.03 MiB的CAD/USD ZIP用于下载功能。应按交付目标打包，不能把全部工作目录大小当作Git仓库负担。 |

截图已通过ASCII临时目录捕获后复制到项目路径，原“中文路径导致截图失败”不再适用于当前实现；中文命名的CMD启动器通过`%~dp0`定位脚本，文件名本身不是已证实缺陷。证据：桥接 `_capture`、根目录启动CMD与 `.gitignore`。

### 本轮剩余验收

- 对热参数连续调整、后台播放和快速动作分别测量端到端延迟；验证动作不丢失、字段版本一致后关闭对应P1项。
- 修正TF剖切边界，补充扇区对齐与源几何变换的自动检查。
- 建立源码版本基线和可配置的本机依赖路径；物理模型接入与上游架构接入须分别验收，不能由界面演示通过代替。
