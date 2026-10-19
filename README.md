# EU-DEMO 聚变数字孪生

基于 Bluemira EU-DEMO-like 概念设计的工程演示：OpenUSD 装配、Warp CUDA 计算、NVIDIA Omniverse RTX 实时渲染，经 WebRTC 推流到浏览器。

> 几何与磁平衡来自 Bluemira 开源概念设计；热场、功率分配、Ne 效应与等离子体温度均为**合成演示模型**，不可用于反应堆设计、安全或制造评定。

## 快速开始

需要：Windows、NVIDIA RTX 显卡、Python 3.12（依赖见 `pyproject.toml`）、Omniverse Kit 110.1.3 运行时。

1. 复制 `runtime.example.json` 为 `runtime.local.json`，填写 Python、Kit 路径和扩展目录。
2. 启动：双击 `启动数字孪生.cmd`，浏览器会打开 `http://127.0.0.1:8765`。首次启动约 1 分钟。
3. 停止：双击 `停止数字孪生.cmd`。

| 启动参数 | 作用 |
|---|---|
| `-Port 8766` | 换端口 |
| `-NoBrowser` | 不自动打开浏览器 |
| `-ServerOnly` | 只启动 HTTP 与计算服务，不启动 Kit |

一个 Kit 只服务一个浏览器标签页。画面冻结时先停止再启动，状态会保留。

## 功能

- **装配**：11 个系统、1,458 个部件；隐藏/隔离、两点测量、剖切、爆炸、透明度、5 个预设视角、环绕。
- **物理场**：表面热流（线性/对数）、表面温度、三维磁力线、等离子体截面与体渲染、相对无 Ne 的差值场。
- **工况**：常规/长腿偏滤器 × Ne 开关，20/35/50/65 MW 辅助加热，5 个磁平衡快照，热预算、冷却流量、入口温度、负荷扫描。
- **导出**：工况 JSON、RTX 截图、STEP 与 USD 压缩包。
- **数据导入**：批量工况计算、外部表面场（见下文）。

## 数据导入接口

服务地址 `http://127.0.0.1:8765`，只监听本机。接口支持 JSON 和 CSV（`Content-Type: text/csv`），请求体上限 64 MB。

### 1. 批量工况 `POST /api/import/scenarios`

一次计算 1–32 个工况，返回每个工况的结果摘要。默认不改变当前画面；用 `apply` 指定一个工况 ID，计算后把它显示到画面上。

每个工况只需写与当前状态不同的字段，未写的字段沿用当前值：

| 字段 | 取值 |
|---|---|
| `id` | 工况名，1–64 字符，不可重复（可省略） |
| `design` | `conventional` / `longleg` |
| `equilibrium` | `reference` / `rampup` / `sof` / `eof` / `rampdown` |
| `scenario` | `nominal` / `ramp` / `lowflow` / `highload` |
| `power` | 基准热预算 500–2600 MW（不含辅助加热） |
| `heating` | 辅助加热，20 / 35 / 50 / 65 MW |
| `neon` | `true` / `false` |
| `flow` | 冷却流量系数 0.4–1.4 |
| `inlet` | 冷却剂入口温度 200–400 °C |
| `phase` | 负荷扫描位置 0–1 |

JSON：

```bash
curl -X POST http://127.0.0.1:8765/api/import/scenarios -H "Content-Type: application/json" -d '{"cases":[{"id":"base","heating":50},{"id":"ne","heating":50,"neon":true}],"apply":"ne"}'
```

CSV（`apply` 放在查询参数里，空单元格表示沿用当前值）：

```csv
id,design,equilibrium,heating,neon
conv-off,conventional,rampup,50,false
conv-on,conventional,rampup,50,true
long-off,longleg,rampup,50,false
```

```bash
curl -X POST "http://127.0.0.1:8765/api/import/scenarios?apply=conv-on" -H "Content-Type: text/csv" --data-binary @cases.csv
```

响应：

```json
{
  "cases": [
    {
      "id": "conv-off",
      "inputs": {"design": "conventional", "equilibrium": "rampup", "heating": 50.0, "neon": false, "...": "..."},
      "peak_temperature_C": 2942.97,
      "peak_heatflux_MW_m2": 56.108,
      "peak_divertor_heatflux_MW_m2": 56.108,
      "outlet_temperature_C": 410.9,
      "cooling_margin_C": -2042.97,
      "relative_no_neon_percent": 0.0,
      "power_budget": {"requested_thermal_MW": 2050.0, "...": "..."},
      "strike_points": {"inner": "unresolved", "outer": "intersection_model"}
    }
  ],
  "applied": "conv-on",
  "revision": 1402
}
```

### 2. 表面场 `POST /api/import/surface`

把客户自己的仿真或测点数据（热流或温度）插值到第一壁与偏滤器网格上，用 RTX 显示。导入后画面自动切到对应模式，并一直保留，切换视角、剖切等操作不会清除它；改动热工参数后，导入数据仍覆盖在新的计算结果上。

| 字段 | 说明 |
|---|---|
| `quantity` | `heatflux`（MW/m²）或 `temperature`（°C） |
| `rows` | 每行 `[R, Z, 值]`（轴对称）或 `[x, y, z, 值]`（三维），单位米，坐标系与 CAD 相同（Z 向上，装置中心为原点） |
| `label` | 显示名称，可选 |
| `max_distance` | 网格顶点距最近数据点超过此距离（米）时视为无数据，显示灰色。默认 0.5，范围 (0, 5] |

- 插值方法：最近 4 个数据点的反距离加权。
- 三维数据会折算到一个 20° 扇区，再复制到整圈 18 个扇区。
- 所有网格顶点都离数据太远时，返回 400，画面不变。

JSON：

```bash
curl -X POST http://127.0.0.1:8765/api/import/surface -H "Content-Type: application/json" -d '{"quantity":"heatflux","label":"IR camera","max_distance":0.2,"rows":[[9.05,-6.60,12.4],[9.10,-6.65,18.7]]}'
```

CSV（第一行可为表头，其余参数放在查询参数里）：

```csv
R,Z,q
9.05,-6.60,12.4
9.10,-6.65,18.7
```

```bash
curl -X POST "http://127.0.0.1:8765/api/import/surface?quantity=heatflux&label=IR%20camera&max_distance=0.2" -H "Content-Type: text/csv" --data-binary @surface.csv
```

响应（`coverage` 为有数据的网格顶点比例）：

```json
{"revision": 1403, "imported_surface": {"label": "IR camera", "quantity": "heatflux", "unit": "MW/m2", "mode": "heatflux", "points": 2, "coverage": 0.12, "min": 12.4, "max": 18.7}}
```

查询当前导入：`GET /api/import/surface`。清除导入、恢复模型结果：`DELETE /api/import/surface`。

### 错误

| 状态码 | 含义 |
|---|---|
| 400 | 参数非法，`error` 字段说明原因（批量工况会指明是哪个工况） |
| 413 | 请求体超过 64 MB |
| 500 | 计算失败，详情见 `runtime/server.stdout.log` 和 `runtime/server.stderr.log` |

### 其他接口

| 接口 | 作用 |
|---|---|
| `GET /api/state` | 当前状态、计算结果与渲染器状态 |
| `POST /api/state` | 修改状态，字段同上表，另含 `mode`、`view`、`cutaway` 等，见 [data-contract.md](docs/data-contract.md) |
| `GET /api/export` | 导出当前工况 JSON（含数据来源） |
| `GET /api/download/cad.zip`、`/usd.zip` | 下载源 CAD 与 USD 场景 |

## 架构

```
浏览器 web/ ──REST──▶ 计算服务 app/fusion_twin/ ──state.json + 字段 NPZ──▶ Kit 渲染 kit/
   ▲                                                                       │
   └──────────────────────── WebRTC 视频 + RTWT 数据通道 ◀─────────────────┘
```

| 目录 | 内容 |
|---|---|
| `app/fusion_twin/` | HTTP 服务与协调器 `server.py`、Warp 计算 `compute.py`、物理模型 `physics.py`、导入 `imports.py`、命令协议 `protocol.py` |
| `kit/` | Kit 应用配置、渲染桥接扩展（USD、剖切、IndeX 体渲染）、RTWT 工作流 |
| `web/` | 双语界面 `app.js` 与 WebRTC 推流封装 |
| `assets/` | 源 CAD 与磁平衡、USD 场景、80 组预制工况 |
| `tools/` | 场景构建、工况预制、运行时导入、QA 脚本 |
| `runtime/` | 日志、状态与缓存，不入版本控制 |

服务是唯一能修改状态的组件：浏览器和 RTWT 发来的修改都先经过它校验、计算，再写成不可变的字段快照，由 Kit 读取渲染。物理假设见 [physics-model.md](docs/physics-model.md)。

## 开发

```bash
PYTHONPATH=app python -m unittest discover -s tests
```

```bash
node --test tests/web_ui_state.mjs
```

修改 Kit 扩展后需要重启 Kit。重新生成场景用 `tools/build_scene.py --output-assets <目录>`，再用 `tools/publish_geometry.py` 发布。

## 来源与许可

- [Bluemira](https://github.com/Fusion-Power-Plant-Framework/bluemira)（LGPL-2.1）与 [bluemira-eudemo](https://github.com/Fusion-Power-Plant-Framework/bluemira-eudemo)（MIT）
- [NVIDIA Digital Twins for Fluid Simulation](https://github.com/NVIDIA-Omniverse-blueprints/digital-twins-for-fluid-simulation)

上游版权与许可保留在 `assets/source/provenance/` 和 `web/vendor/`。
