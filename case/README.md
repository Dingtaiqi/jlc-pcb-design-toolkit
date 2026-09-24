# case/ —— 真实案例：90×90mm 双面控制器板（EasyEDA Pro）

工具包里的东西都是从这块板子上磨出来的。这里放**案例本体**：布线的过程文档、脚本、板子文本快照、渲染图、以及最终交付件。

> ⚠️ **隐私提醒**：本目录包含具体产品的设计数据（网表、Gerber、坐标、器件型号）。
> 如果这个仓库是**公开**的，请自行评估是否要把本目录移出（或改成私有仓库）。
> 只想要工具、不要案例，可以直接删掉整个 `case/` 目录。

## 这块板子

| 项 | 数值 |
|---|---|
| 板框 | 90 × 90 mm，含 8 点异形挖空（滚轮区）+ 2 个 NPTH |
| 层数 | 4 层：**TOP – GND(内1) – VCC(内2) – BOTTOM**（层压顺序不可换） |
| 元件 | 172（166 实装 + 6 个 Mark 点），双面贴片：TOP 154 / BOTTOM 12 |
| 网络 | 125（含 3 个 net-tie：PGND→GND、AGND→GND、GND_BK→PGND） |
| 铜 | **1926 条线 / 268 个过孔 / 656 个焊盘 / 4 块铺铜** |
| 最小钻 | **0.305 mm**（免加钱档 0.3mm 档；过孔 16/12mil，最小环宽 0.051mm） |
| 孔到孔 | 最小 **0.312 mm**（≥ 厂规 0.25 mm） |
| **DRC** | **0 违规**（3 次采样并集、覆盖率 100%） |
| Mark 点 | 每面 3 个：铜点 Ø1.0mm / 开窗 Ø2.0mm / 周边禁铜 2.2×2.2mm |

## 目录导航

| 路径 | 内容 |
|---|---|
| `PIPELINE.md` | ★ **布线全流程**（9 个阶段 + 每阶段的坑），这是"方案"正文 |
| `docs/DELIVERY.md` | 交付总说明（含天线净空、层压、阻抗等实测结论） |
| `docs/STITCH_LOG.md` / `REROUTE_LOG.md` | 补线与返工的完整流水账（含每次判据） |
| `docs/DRC_FULL_REPORT.md` | DRC 全量导出报告（含 1400 条错误的根因分析） |
| `docs/RESUME.md` / `FINAL_STATE.md` / `HANDOVER.md` | 断点续跑说明与最终状态 |
| `docs/TOOLS.md` | 本案例用到的工具清单 |
| `layout-scripts/` | 33 个按阶段精选的脚本（放置校验 / A* 布线 / 扇出 / RF / 补线 / DSN-SES 流水线 / 校验） |
| `board_snapshot.json` | **板子文本快照**：全部线/过孔/焊盘的坐标与网络（可 diff、可复算） |
| `images/` | 板子渲染图（顶层/底层）与 Mark 点实测图 |
| `deliver/` | 最终交付件：Gerber zip、BOM、贴片坐标、装配清单、工艺要求、换料说明 |

## 复现快照

```bash
# 板子文本快照就是 extract_live.py 的输出(live.json)
python pcbai.py snap && cp live.json case/board_snapshot.json

# 交付件重新导出
python pcbai.py export gerber bom pickplace
```

## 这块板子踩过的"经典坑"（详见 ../docs/PITFALLS.md）

- 焊盘的 `rotation` 是**弧度**不是度 → 旋转焊盘判错，A* 会得出"布不出来"的假结论
- 铺铜 `rebuildCopperRegion()` **反复调用会丢铜** → 必须每块只调一次、中间留间隔
- 网络规则被注入 379 条 `copilot_router_*` → DRC 爆出 1400 条错误
- DSN 导出丢线/边界自交 → 自由布线器永远布不通 PT1/LED1_3
- SES 导入忽略线宽、把内层铜落到 21/22 层 → 421 条间距错误
- 孔到孔**同网也查**（同网孔挨太近一样钻不出来）
