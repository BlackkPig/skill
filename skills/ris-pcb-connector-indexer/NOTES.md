# 备注 / 维护记录

## v1.0.0 — 2026-09-02

该技能来自一次实际 RIS 阵面索引任务，需求是：从 Altium `.PcbDoc` 中把阵面控制点按**正视图左→右、上→下**编号，并沿实际铜层连接关系追到连接器具体引脚，最后生成可检索/可反查的 Excel。

### 首版实板回归结果

- 参考阵面：12 × 24，共 288 路。
- 目标连接器：J8。
- 追踪结果：288 / 288 路成功匹配。
- 唯一性：288 个 RIS 控制点对应 288 个不同的连接器引脚。
- 用户提供的 3 个首部 anchor 均通过。
- 原始 `.PcbDoc`、完整 288 路映射表和生成的 Excel **没有提交到公开仓库**，避免无意公开板级设计数据。

### 当前实现边界

1. 已验证的是含 `Components6 / Pads6 / Vias6 / Tracks6` 的 Altium PcbDoc 流格式。
2. 目前 connector SMD pad 的命中使用轴对齐外接矩形；极端旋转/异形 pad 建议人工复核或后续扩展 pad rotation/shape 解析。
3. 追线采用“端点接触”保守策略，优先避免假短路；若某设计存在一条 track 穿过 via/pad 但没有在该处切段，可能需要扩展为铜面积相交模型。
4. 如果同一连接器还有大量其它 Top→Bottom via，应结合 `--expected-count`、`--rows/--cols`、`--bbox` 或显式 `--source-span` 限定 RIS 控制区。
5. 任何未匹配、重复或歧义都必须暴露出来，禁止按引脚规律补全。

### 后续优先升级方向

- 解析 pad rotation / custom shape。
- 支持更多 Altium PcbDoc stream 版本。
- 增加自动 ROI / 多阵面识别。
- 增加“二极管 pad → 控制 via → 连接器 pin”的元件级验证，而不只以 source via 为起点。
- 对多连接器分区阵面支持一次性输出多个 Excel 分表。
