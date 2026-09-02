# RIS PCB Connector Indexer

从 Altium `.PcbDoc` 直接追踪 RIS 阵面控制点到连接器引脚，并按阵面正视图生成稳定的行列索引。适合 1-bit / 2-bit RIS、PIN 二极管阵面、可重构超表面及其它“阵面大量独立控制线 → 板端连接器”的硬件。

核心原则：**不根据截图猜线、不按引脚规律外推，只认 PcbDoc 实际铜层连通关系。**

## 解决的问题

例如用户说：

> 阵面上有 288 路控制信号，正视图从左到右、从上到下编号 1–288。请告诉我每一路最终接到底层 J8 的哪个引脚，并输出 Excel。

本技能执行：

`PcbDoc解析 → 几何连通图 → 控制via识别 → J8引脚追踪 → 行列排序 → 唯一性/anchor校验 → Excel交付`

## 快速使用

```bash
cd skills/ris-pcb-connector-indexer
python -m pip install -r requirements.txt

python scripts/inspect_pcb.py /path/to/board.PcbDoc

python scripts/trace_ris_connector.py /path/to/board.PcbDoc \
  --connector J8 \
  --expected-count 288 \
  --rows 12 \
  --cols 24 \
  --anchor 1=<known_pin> \
  --out-dir outputs
```

提取器会生成：

- `ris_connector_mapping.json`
- `ris_connector_mapping.csv`
- `ris_connector_connector_pins.csv`
- `ris_connector_diagnostics.json`

随后由 Skill 按 `references/excel_layout.md` 生成最终 `.xlsx`。

## 自动判断 source via

如果不写 `--source-span`，程序会：

1. 找所有能唯一追到目标连接器单一引脚的 via；
2. 按 `(start_layer, end_layer)` 分组；
3. 如果提供 `--expected-count`，优先选择数量恰好匹配的 span；
4. 否则优先 `1:32`（Top→Bottom）；
5. 若仍有多解，报错要求显式指定，不猜。

常用限定：

```bash
--source-span 1:32
--bbox 20,250,190,410
--row-tolerance-mm 0.25
```

## 输出 Excel

最终 Excel 固定建议 4 个 Sheet：

- `RIS路索引`：序号、阵面行列、坐标、连接器、引脚、via 信息。
- `阵面映射矩阵`：按实际阵面位置显示 `序号 / 引脚`。
- `连接器反查`：从 connector pin 反查 RIS 序号。
- `说明`：数据源、排序、容差、校验结论、限制。

详见 `references/excel_layout.md`。

## 安全与工程数据

`.gitignore` 默认屏蔽 `.PcbDoc`、Excel 和 mapping 输出。除非用户明确要求，**不要把客户/实验室 PCB 文件或完整引脚映射提交到公开 GitHub**。

## 回归基线

首版已在一个 12×24 / 288 路 RIS PcbDoc 上验证：288 路全部唯一映射，用户提供的三个首部 anchor 通过。原始板文件与完整映射未公开。详见 `NOTES.md`。

## 测试

```bash
pytest -q
```

## 文件结构

```text
ris-pcb-connector-indexer/
├── SKILL.md
├── README.md
├── NOTES.md
├── requirements.txt
├── scripts/
│   ├── cfb.py
│   ├── altium_pcb.py
│   ├── trace_ris_connector.py
│   ├── inspect_pcb.py
│   └── summarize_mapping.py
├── references/
│   ├── tracing_rules.md
│   └── excel_layout.md
├── examples/
│   └── config.example.json
└── tests/
    └── test_grid.py
```
