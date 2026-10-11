# 首版验收记录

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
