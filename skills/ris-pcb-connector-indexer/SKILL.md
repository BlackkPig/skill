---
name: ris-pcb-connector-indexer
description: 从 Altium PcbDoc 中按 RIS 阵面物理顺序索引控制点，沿实际铜层几何连接关系追踪到底层/板端连接器具体引脚，并生成可审计、可反查的 Excel。适用于 PIN 二极管 RIS、可重构超表面及大规模阵面控制线索引。
version: 1.0.0
author: BlackkPig
tags:
  - RIS
  - PCB
  - Altium
  - PcbDoc
  - connector
  - pin-mapping
  - hardware
license: MIT
---

# RIS PCB → Connector 引脚索引 Skill

## 任务目标

本技能用于解决一种高频硬件工程任务：用户给出 RIS / 超表面 `.PcbDoc`（通常还会给阵面截图），要求把每个二极管控制点或控制 via 按阵面物理位置编号，并追踪到连接器的真实引脚，最后交付 Excel。

**最重要原则：连接关系只以 PcbDoc 实际铜层连通为准。截图只辅助确认方向/ROI，不能用视觉猜线，更不能按前几个引脚的数值规律外推后续 288 路。**

## 触发条件

当用户表达以下意图时触发：

- “帮我把 RIS 的 288 路对应到 J8/A21 这类连接器引脚。”
- “从 PcbDoc 找每个二极管控制线最终接到哪个 connector pin。”
- “阵面从左到右、从上到下编号，输出 Excel 索引。”
- “我有 1-bit/2-bit RIS/超表面阵面，想做控制线 ↔ 连接器反查表。”

## 输入

| 输入 | 必填 | 说明 |
|---|---:|---|
| `.PcbDoc` | 是 | 真实追线数据源 |
| 阵面截图/示意图 | 否 | 仅用于确认正视方向、控制点类型或 ROI |
| connector 位号 | 推荐 | 如 `J8`；未给时从 Components 中保守识别大引脚数连接器候选 |
| 总路数 | 推荐 | 如 288；用于 source-via span 自动判定和硬校验 |
| 行 × 列 | 推荐 | 如 12 × 24；用于阵面结构硬校验 |
| anchor | 否 | 如 `1=<已知引脚>, 2=<已知引脚>`，用于回归验证，不用于推算 |

## 用户既定编号规范

除非用户明确覆盖，否则固定使用：

1. **阵面正视 / Top View**。
2. **先从左到右**：同一行按 X 坐标升序。
3. **再从上到下**：行按 Y 坐标降序。
4. 左上角 = 1；之后连续编号到 N。

该方向是交付 Excel 与矩阵 Sheet 的唯一默认方向，不能擅自翻转成 Bottom View。

## 必须执行的工作流

### Step 1：定位输入文件，不用截图替代 PcbDoc

- 优先使用对话中实际上传/挂载的 `.PcbDoc`。
- 若只有图片而没有 PcbDoc，说明只能做视觉编号，**不能可靠给出 connector pin**，应要求板文件或可验证网表/ODB++/IPC-2581。
- 不对 PcbDoc 做 OCR。

### Step 2：确定 connector、路数、阵面规模

优先从用户文字获取，例如：`J8 / 288 / 12×24`。

如果 connector 未给：

- 解析 `Components6`；
- 统计各 component 的命名 pad 数；
- 若只有一个明显大引脚连接器候选，可自动选并在结果中说明；
- 若多个候选都合理，列出候选后再问，不能猜。

### Step 3：运行几何追线器

先阅读 `references/tracing_rules.md`，然后运行：

```bash
python scripts/trace_ris_connector.py <board.PcbDoc> \
  --connector J8 \
  --expected-count 288 \
  --rows 12 \
  --cols 24 \
  --out-dir <working_dir>/outputs
```

若用户提供 anchor，逐个加入：

```bash
--anchor 1=<known_pin> --anchor 2=<known_pin>
```

**anchor 只用于验真，不允许用于外推。**

### Step 4：只有全部硬校验通过才进入 Excel

必须确认：

- 映射路数符合 expected count；
- 阵面 row/col 数量符合要求；
- 每一路只对应一个 connector pin；
- RIS 使用的 connector pin 全部唯一；
- 所有 anchor 通过；
- diagnostics 为 `PASS`。

任何一项失败：

- 不得补齐；
- 不得按“引脚似乎每次 +5”之类规律推算；
- 输出失败项和诊断建议（source span / bbox / connector / row tolerance）。

### Step 5：生成 Excel

阅读 `references/excel_layout.md`。

在具备宿主 spreadsheet 工具的环境中，必须用宿主的表格工具创建 `.xlsx`。在 ChatGPT 工具环境中，遵循 spreadsheet skill / `artifact_tool` 的规范，不使用图片代替表格数据。

最终至少 4 个 Sheet：

1. `RIS路索引`
2. `阵面映射矩阵`
3. `连接器反查`
4. `说明`

Excel 中必须写明排序方向和校验结论。

### Step 6：最终自查

至少抽查：

- 前 3–10 路；
- 每一行首尾；
- 最后 3–10 路；
- 用户 anchor；
- connector 反查是否与主表一致。

如果工具允许，检查 Excel 关键范围并确认没有结构/公式错误。

## 追线器的技术策略

本技能不是依赖 net name。它专门考虑实验室/科研板常见情况：大量 track/via 处于 `No Net` 或手工布线状态。

因此采用：

`PcbDoc CFB解析 → Components/Pads/Vias/Tracks → 铜层几何连通图 → connector root → unique-pin source via → 阵面排序`

为了降低假短路，默认采用**保守端点接触模型**：track 必须在 via/pad 处终止，或某 track 端点落在另一 track 上，才视为电气连通。详细规则见 `references/tracing_rules.md`。

## 常见故障与处理

### 1. source via 数量多于路数

先看 diagnostics 中的 via span histogram。依次使用：

- `--source-span 1:32`
- `--expected-count N`
- `--rows R --cols C`
- 根据截图/坐标给 `--bbox minx,miny,maxx,maxy`

### 2. 某一路没有 pin

可能是：

- 连接线在 via/pad 处没有切段；
- pad 旋转/异形导致当前轴对齐命中模型漏判；
- 走线用了尚未解析的对象类型；
- 用户选错 connector。

不要猜，先输出对应 via 坐标和 diagnostics。

### 3. 某一路连到多个 pin

这表示连通图发现公共网络、实际短接或几何误判。该路必须标为歧义并停止完整交付，除非能通过更精确几何模型消歧。

### 4. 正反面方向争议

默认编号永远按用户看到的阵面正视 Top View。连接器在 Bottom Layer 并不意味着编号表要左右镜像。

## 数据与隐私规范

- 原始 PcbDoc 是板级设计资产；**除非用户明确要求，不要上传到公开仓库、网页或第三方服务**。
- GitHub skill 仓库只提交脚本、规则、匿名示例和维护备注。
- `.gitignore` 已默认排除 PcbDoc、Excel 与 mapping 输出。

## 输出给用户的简洁说明模板

完成时应说明：总路数、连接器、排序规则、唯一性、anchor 是否通过，并提供 Excel 文件链接。不要在正文刷屏粘贴 288 行，除非用户要求。
