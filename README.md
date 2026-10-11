# EU-DEMO 聚变工程数字孪生

基于 Bluemira 框架本地生成的 EU-DEMO-like 概念 CAD，使用 NVIDIA Omniverse RTX 路径追踪、OpenUSD 装配和 NVIDIA Warp CUDA 计算。本机 Windows 演示原型，浏览器中英文切换，不含 AI 代理。尚未接入 RTWT / Kit-CAE 工作流，物理有效性未经验证。

## 启动

双击 **启动数字孪生.cmd**，打开 `http://127.0.0.1:8765`。首次 Kit 启动需要等待着色器与场景加载。一个 Kit 会话同时使用一个浏览器串流页面。

也可运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-demo.ps1
```

双击 **停止数字孪生.cmd** 关闭服务，也可运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\stop-demo.ps1
```

应用目前复用本机已有运行环境：

- Python：`D:/nvcode/fusion-env/Scripts/python.exe`，3.12.12。
- Kit：`D:/nvcode/fusion-twin/_build/windows-x86_64/release/kit/kit.exe`，110.1.3。
- NVIDIA WebRTC SDK：5.6.0，已在 `web/vendor/` 构建，无需启动前端开发服务器。
- RTX 5070 Ti，串流保持2560×1440，目标30 FPS，关闭帧生成。交互时内部渲染1920×1080；相机停止0.75秒后恢复原生2560×1440。
- 渲染采用 RTX Path Tracing 与 OptiX 降噪，每帧1个样本、静止最多积累256个样本；每次场景变化重新积累采样。截图使用高清尺寸。
- 浏览器从渲染器读取真实分辨率；截图保留原生像素。画质升级后刷新已打开的页面。

WSL2 中生成的资产已经复制进本项目，日常演示无需启动 WSL。新机器安装 Python 包时以 `pyproject.toml` 中锁定版本为准；Kit 及扩展需另行配置，受 NVIDIA 对应许可约束。

## 演示流程

1. **工程装配**：全堆总览、正视、俯视、剖面和偏滤器相机，支持拖动、缩放与环绕。
2. **装配树**：选择系统、隐藏、隔离、显示尺寸与材料，查看或下载源 CAD。
3. **剖开与爆炸**：按20°真实 CAD 扇区剖开；爆炸视图分离装配，透明度辅助内部观察。
4. **场数据**：表面温度、热流密度、磁力线和等离子体截面温度；热场与工况控件联动。
5. **工况对比**：额定、热负荷爬升、低冷却流量和高热负荷，显示当前工况相对额定工况的差值。
6. **测量与导出**：部件包围盒尺寸、两点距离、当前工况 JSON、实际 RTX 截图、CAD/USD ZIP。

## 模型与数据

- 11 个部件系统，完整装配约 1,458 个 CAD 部件实例、1,451,304 个三角形。
- 双设计资产保留 conventional 和 longleg；当前交互演示固定 conventional，确保 CAD、磁平衡和热场对应。
- `assets/source/eudemo/` 保留原始 STEP、命名网格、机器参数和磁平衡。
- `assets/scene/fusion.usda` 是相对引用完整的场景入口；配套组件层在同目录。
- `assets/scenarios/` 保留四组可复现的预制工况、场数组和计算结果；交互时通过 Warp 重新计算当前参数。
- 原始 STEP 是扇区模型；完整环形装配由 USD 重复实例组织。CAD ZIP 保留原始 STEP 语义。
- `assets/source/provenance.json` 记录上游 commit、生成脚本、已知单位问题及资产 SHA-256。源参数中 `P_fus=1994.6` 的 `W` 标签有问题，应用采用明确设置的演示功率，不使用该标签。

热流和温度是**合成边界条件下的降阶演示计算**，用于交互可视化。表面热流没有归一成全堆功率守恒解；独立冷却回路假设用于显示出口能量平衡。900°C 为演示阈值。磁力线由源磁平衡数值积分，使用 Bφ=fvac/R 近似。没有传感器遥测或 AI 预测。界面的数据说明可查看这些假设。

## 工程结构

```text
app/fusion_twin/    HTTP服务、状态校验、Warp场计算
web/               双语界面、官方NVIDIA串流SDK封装
kit/               RTX应用与USD交互扩展
assets/            CAD源、来源记录、场景、导出包
tools/             场景重建、导出打包、Kit启动与浏览器验收
tests/             几何、物理、CPU/GPU及状态测试
runtime/           本次运行状态、计算场、日志与截图（不入版本管理）
```

状态与字段协议见 `docs/data-contract.md`。界面控制经本地 HTTP 服务写入原子状态文件；Kit 扩展在 USD 会话层应用修改，原始资产保持可重建。

## 开发与验证

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'app'
& D:\nvcode\fusion-env\Scripts\python.exe -m unittest discover -s tests -v
npm run check:web
npm run build:streamer
```

场景与下载包重建：

```powershell
& D:\nvcode\fusion-env\Scripts\python.exe tools/build_scene.py
& D:\nvcode\fusion-env\Scripts\python.exe tools/prepare_exports.py
& D:\nvcode\fusion-env\Scripts\python.exe tools/bake_scenarios.py
```

浏览器验证工具在 `tools/qa/`，使用已安装的 Microsoft Edge；它不占用日常浏览器配置。避免与演示页面同时争用单个视频会话。

历史记录包含25项自动测试、40项浏览器功能检查及实际双点测量，不能替代物理验证或动态性能验收。2026-10-12增加接收、解码和实际呈现帧率检查；自适应画质在默认GPU浏览器的6秒环绕测试中呈现约29.97 FPS、丢帧0。详细限制和评审核验见 [验收记录](docs/verification.md)。

## 来源

- [Bluemira EU-DEMO](https://github.com/Fusion-Power-Plant-Framework/bluemira-eudemo)
- [Bluemira](https://github.com/Fusion-Power-Plant-Framework/bluemira)
- [NVIDIA Digital Twins for Fluid Simulation](https://github.com/NVIDIA-Omniverse-blueprints/digital-twins-for-fluid-simulation)

上游版权与许可文件保留在 `assets/source/provenance/` 和 `web/vendor/`。NVIDIA 名称用于注明实际采用的技术。
