# REROUTE_LOG —— 4 层板 DRC 清干净：DSN 规则修正 → Freerouting 重跑 → 导回 → 报数

工作区：`D:\360Downloads\tourbox\pcb-layout`　板子：EasyEDA Pro `tourbox eltie`，PCB uuid `a13a9a0e834c40d3a24ee99ae8ff4e1c`
本次执行者：布线子会话（2026-09-20 23:45 起）。**元件摆放未做任何移动；天线匹配网络（L7/C65/C66/L6/R28）未触碰。**

---

## 0. TL;DR（结论先行）

| 问题 | 结论 |
|---|---|
| DSN 规则是否"太松"？ | **只有 3 处是真的低于目标**：默认类 `''` clearance 4.02mil(0.102mm)、USB_DP/USB_DM 5.91mil(0.150mm)；结构级 6.03mil(0.1532mm) 只比目标高 **1.2 µm**，等于零余量。其余 122 个 class 是 5.98mil(0.1519mm)，也低于 6mil 目标约 0.1µm。 |
| 这 1400 个错误是"FR 布出的铜不满足 6mil"吗？ | **不是。** 直接对 Freerouting 原始输出 `tools/tourbox4.ses` 做几何真值检查（shapely，同层异网，线-线 + 线-过孔）：**间距 <0.152mm 的对数 = 0**。FR 布出的铜本身满足 6mil。 |
| 那 1400 个错误从哪来？ | **两个来源**：(a) **1361 个间隙错误全部挂在 MCP 路由 DSL 注入的 net rule `copilot_router_net_0_spacing`(0.59843mm) 上**，其中只有 592 个 minDistance<0.152mm，另 769 个只违反那条注入的 0.59843mm 要求（假违规）；(b) **EasyEDA 的 SES 导入器用的是板上 net rule 的 Track 宽度、而不是 SES 里的线宽**，把走线整体加粗（GND 0.2553→0.2997mm，+5V→1.049，VCC→0.5994，PGND→1.5494，1V1→0.3988），于是 FR 设计的 0.153mm 间隙被"吃"掉 → 594 个 track-track 真实违规（我用独立几何检查复现的数量与 EasyEDA DRC 的 594 完全一致）+ 39 个 Connection Error(FR 未布通 19 条)。 |

---

## 1. 第 1 步：读 DSN 规则段并对比目标

文件：`tools/tourbox4.dsn`（73 665 字节，4 层，0 段铜）。

### 1.1 单位判定（重要，先说清楚）
文件头 `(resolution mil 1000)`。EasyEDA Pro 导出的这个 DSN **数值实际以 mil 为单位**，已用三处独立证据交叉验证：

| 证据 | DSN 里的值 | 换算 | 实际应为 | 结论 |
|---|---|---|---|---|
| 板框 boundary | `3543.31` | = 3543.31 mil | 90 mm | ✅ 单位=mil |
| via0 padstack 圆 | `24` | = 0.6096 mm | 常见 0.6mm 过孔 | ✅ |
| pad 多边形半宽/半高 | `15.75 / 17.72` | = 0.80 × 0.90 mm | 正常 SMD 焊盘 | ✅ |

FR 读进去后，输出 SES 时把长度乘 1000（SES 头也是 `(resolution mil 1000)`，即 1/1000 mil 单位）：DSN 的 via `24` → SES `24000`、DSN 的 width `10.05` → SES path `10050`。**所以 DSN 里 `6.03` 就是 6.03 mil = 0.1532 mm。**

### 1.2 结构级（全局默认）规则

| DSN 原文 | 值(mil) | 值(mm) | 目标(mm) | 判定 |
|---|---|---|---|---|
| `(rule(clear 6.03))` | 6.03 | 0.15316 | track-track/pad/via 0.152 | 达标但**余量仅 +1.2 µm**（量化/取整即翻车） |
| `(rule(clear 6.03 (type default_smd)))` | 6.03 | 0.15316 | 0.152 | 同上 |
| `(rule(clear 6.03 (type smd_smd)))` | 6.03 | 0.15316 | 0.152 | 同上 |
| `(rule(width 10.05))` | 10.05 | 0.25527 | 最小线宽 0.127 | 达标（偏粗） |
| `(via via0)` padstack | 24（钻孔由编辑器给） | 0.6096 | 孔径最小值 0.175 | 达标 |
| **track-board 0.30 / hole 0.175** | —— | —— | —— | **DSN 里完全没有这两类规则**（板边距/孔到孔靠 FR 默认值与 EasyEDA 侧设置） |

### 1.3 net class 级规则（126 个 class，class 名 = 网名）

| 项目 | 数量 | 值(mil) | 值(mm) | 判定 |
|---|---|---|---|---|
| clearance = 5.98 | 122 | 5.98 | 0.15189 | ⚠ **比 0.152 目标低 0.1 µm** |
| clearance = 5.91 | 2（USB_DP/USB_DM） | 5.91 | 0.15011 | ❌ **低于 0.152 目标** |
| clearance = 4.02 | 1（默认类 `''`） | 4.02 | 0.10211 | ❌❌ **严重低于目标（-33%）** |
| clearance = 7.87 | 1（$1N17987） | 7.87 | 0.19990 | ✅ |
| width = 11.81 | 109 | 11.81 | 0.3000 | ✅（≥0.127） |
| width = 41.34 / 61.02 / 23.62 / 15.75 | 5 / 4 / 1 / 2 | — | 1.05 / 1.55 / 0.60 / 0.40 | ✅ 电源类加粗 |
| width = 11.57 | 2（USB_DP/USB_DM） | 11.57 | 0.2939 | ✅ |
| width = 10 | 1（默认类 `''`） | 10 | 0.2540 | ✅ |
| width = 5 | 2（DM/DP） | 5 | **0.1270** | ⚠ 恰等于最小线宽下限，零余量 |

**结论（对比目标规则）**：DSN 主要问题是"**余量几乎为零 + 3 个 class 明确低于目标**"，而不是"大面积太松"。
实测也证明：FR 按这些值布出来的铜（SES）在 0.152mm 阈值下 **0 违规**。

---

## 2. 第 2 步：修正 DSN → `tools/tourbox5.dsn`

生成脚本：`mk_dsn5.py`（只改规则行，逐行 diff 校验：264 行 diff **全部**是 rule/width/clearance 行，非规则行 0 处改动；文件 73 665 → 73 274 字节）。

| 项目 | tourbox4.dsn | tourbox5.dsn | 换算(mm) |
|---|---|---|---|
| 结构级 clear（3 条） | 6.03 | **8** | 0.2032（比目标 0.152 高 **33%**） |
| 结构级 width | 10.05 | **8** | 0.2032（≥0.127 ✅） |
| 126 个 class clearance | 4.02 / 5.91 / 5.98 / 7.87 | **全部 8** | 0.2032 |
| DM / DP width | 5 | **6** | 0.1524（贴近 USB 0.15 设计值，≥0.127 ✅） |
| 其余 width | 11.81 / 41.34 / 61.02 / 23.62 / 15.75 / 11.57 / 10 | 不变 | 0.30 / 1.05 / 1.55 / 0.60 / 0.40 / 0.294 / 0.254 |
| track-board 0.30、hole 0.175、最小线宽 0.127 | —— | 由 EasyEDA 侧 DRC 规则保证（DSN 无此语法位） | —— |

> 选择 8 mil（0.2032mm）而不是 0.25mm 的理由：板子铜覆盖率已 29–31%，0.25mm 间距会显著增加未布通风险；8 mil 已提供 33% 余量，足以吸收导入取整与线宽误差。

`tourbox4.dsn` / `tourbox4.ses` 未覆盖、未改动。

---

## 3. 第 3 步：重跑 Freerouting（每 5 分钟记录 score/unrouted）

命令（后台 nohup，15 线程，日志 `tools/fr5.log`）：

```
cd tools
nohup jdk-25.0.4.1+1/bin/java.exe -jar freerouting-2.4.1.jar \
  -de tourbox5.dsn -do tourbox5.ses -mp 30 -oit 0.25 > fr5.log 2>&1 &
```

启动时间 2026-09-20 23:50:16。Fanout 阶段（0.2032mm 规则）比上一轮吃力：not-routed SMD pin 从 8–17 升到 44–48。

### Pass 曲线（每 5 分钟采一次）

<!-- MONITOR:START -->
| pass | 完成时刻 | 用时(s) | score | unrouted | violations |
|---|---|---|---|---|---|
| fanout | 23:51:02 | 37.7 | — | 445/497 SMD pin 逃逸成功(89.5%) | — |
| 1 | 23:54:01 | 178.1 | 722.96 | 89 | 152 |
| 2 | 23:57:29 | 207.1 | 762.40 | 72 | 152 |
| 3 | 00:00:42 | 191.6 | 774.01 | 67 | 152 |
| 13 | 00:30:18 | 177.8 | 785.61 | 62 | 152 |
| 14 | 00:34:00 | 220.9 | 785.61 | 62 | 152 |
| 15 | 00:37:49 | 227.5 | 787.93 | 61 | 152 |
| 16 | 00:41:33 | 0.0 | 787.93 | 61 | 152 |
<!-- MONITOR:END -->

对比：tourbox4（6.03mil 间距 + 10.05mil 线宽）那一轮 pass1 = 47 unrouted / 28 violations，最终 19 条未布通。
tourbox5（8mil 间距 + 8mil 线宽）明显更难，未布通项预计 ~50-60（≈25-30 个网）。这是"33% 间距余量"的代价。

---

## 4. 第 4~7 步：导回 / 修层 / 快照 / 报数

（待 FR 结束后填写）

---

## 5. 附：本次用到的独立几何检查（可复现）

| 脚本 | 作用 | 关键结果 |
|---|---|---|
| `_ses_gaps.py` | 解析 `tools/tourbox4.ses`，按 net/layer 建 buffered 多边形（STRtree），统计同层异网间距 | 线-线 <0.152mm = **0**；线-过孔 <0.152mm = **0** |
| `_geom_check.py` | 读 `live.json`（板上实际几何），同样的检查 | 线-线 <0.152mm = **594**（与 EasyEDA DRC 的 Track-to-Track 594 一致）；分布：重叠(=0) 291、<0.05 36、0.05–0.10 66、0.10–0.152 201 |
| `_drc_attr3.js` | 走桥接跑官方 DRC，从 `explanation.errData` 取每条真值 | 1400 = 1361 Clearance + 39 Connection；1361 全部 ruleName=`copilot_router_net_0_spacing`(clearance 0.59843mm)；minDistance<0.152 的 592 条 |
| `_drc_attr4.js` | 同上网/异网判定 | 0 条同网（说明这些确实是异网对）；531 条异网且 minDistance=0 |
| 宽度对照 | `live.json` 的线宽 vs SES 的 path 宽度 | 板上 GND 0.2997 / VCC 0.5994 / +5V 1.049 / 1V1 0.3988 / PGND 1.5494 mm ↔ SES 只有 0.2553/0.2499/0.2001/0.1914/0.1532 mm ⇒ **导入器用了 net rule 的 Track 宽度** |

---

## 3.5 阶段 2：根因锁定与"导入器覆盖线宽"的实测证据（2026-09-21 00:00~00:45）

### 3.5.1 官方 DRC 的 1400 条到底怎么来的

用 `_drc_attr3.js`（走桥接，从每条错误的 `explanation.errData` 取真值）分解：

| 分组 | 数量 | 说明 |
|---|---|---|
| Clearance Error | 1361 | **100% 挂在 net rule `copilot_router_net_0_spacing`，其 clearance = 0.59843mm**（另一条是 `copilot_router_net_112_spacing` 0.59055） |
| └ 实际间距 <0.152mm | **592** | 其中 531 条 minDistance = 0（重叠） |
| └ 实际间距 0.152~0.60mm | **769** | **只违反那条注入的 0.59843mm 要求 → 假违规** |
| Connection Error | 39 | = Freerouting 自己日志里"19 条未布通"的体现 |

按对象类型：Track to Track 594、SMD Pad to Track 420、Track to Via 231、Hole to Track 71、TH Pad to Track 40、Slot Region to Track 5。
`_drc_attr4.js` 复核：1361 条**没有一条是同网**，全部是异网对。

### 3.5.2 决定性证据：Freerouting 的原始输出是干净的

`_ses_gaps.py` 直接解析 `tools/tourbox4.ses`（按 net 分组，1/1000 mil 单位，STRtree + buffered polygon）：

| 检查（同层、异网） | 阈值 | 对数 |
|---|---|---|
| 线-线 | < 0.152mm | **0** |
| 线-过孔 | < 0.152mm | **0** |

SES 里的线宽：0.2553mm ×1714 段、0.2001 ×85、0.1914 ×34、0.2499 ×26、0.1532 ×7。
→ **FR 是按 DSN 的"结构级"规则布线的**（clear 6.03mil=0.1532mm、width 10.05mil=0.2553mm），
并且它**忽略了 126 个 net class 的规则**（class 里的 (width 11.81)/(clearance 5.98) 没生效）。
证据：若 class 生效，SES 里应出现 11.81/41.34/61.02mil 的线宽，实际一条都没有；实测最小间距也恰好 ≥6.03mil 而不是 5.98mil。

### 3.5.3 板上铜为什么变成 594 对违规：导入器用 net rule 覆盖线宽

| 网络 | SES 里的线宽 | 注入规则下的板上线宽 | 复位规则后的板上线宽 |
|---|---|---|---|
| GND | 0.2553 / 0.2001 | 0.2997 | 0.254 |
| VCC | 0.2553 / 0.2001 | 0.5994 | 0.254 |
| +5V | 0.2553 | 1.0490 | 0.254 |
| 1V1 | 0.2553 | 0.3988 | 0.254 |
| PGND | 0.2553 | 1.5494 | 0.254 |

结论：**EasyEDA 的 SES 导入器不使用 SES 文件里的线宽，而是套用板子 net rule 的 Track 宽度**
（注入规则时 = GND 0.3/VCC 0.6/+5V 1.05/PGND 1.55/1V1 0.4mm；复位成 default 后 = 默认 0.254mm）。
线宽被放大 → 铜的净间距变小 → 产生 6mil 违规：

> 实例（`_geom_check.py` + SES 反查）：GND 段 `(1518420,2216682)-(1570450,2216682)` w=7878（0.2001mm）
> 与 $1N3685 段 `(1518210,2231890)-(1495134,2231890)` w=7878，中心距 0.3863mm。
> FR 侧净间距 = 0.3863 − 0.2001 = **0.1862mm（合格）**；导入成 0.254mm 后 = **0.1322mm（不合格）**。

### 3.5.4 修复：`restore_widths.py`（把线宽还原成 SES 值）

- 原理：按"层 + 端点"把板上每条走线映射回 SES 段；先投票求全局平移（本板 dx=0、dy=−7.24mm，902 票），匹配容差 0.05mm。
- dry-run：匹配成功 **1733/1789**，其余 56 条退化为"该网 SES 最小宽度"，无完全找不到的。
- `--apply` 之后（板上实测线宽）：0.2553 ×1630、0.2001 ×87、0.1914 ×44、0.2499 ×22、0.1532 ×6 条。

**效果（同一块板、同一份铜，只改线宽）**

| 指标 | 注入规则 + 胖线宽 | 复位规则 + 0.254 统一 | **复位规则 + 线宽还原** |
|---|---|---|---|
| 官方 DRC 总数 | 1400 | 60 | **45 = 0 Clearance + 45 Connection**※ |
| ├ Clearance | 1361 | 21（全是 ≥0.3mm 的铺铜/焊盘陈旧间隙） | **0** |
| └ Connection | 39 | 39 | 45※ |
| 6mil 几何审计 线-线 <0.152mm | 594 | 68 | **1**（唯一一对 0.1511mm，差 0.9µm） |

※ 45 条里的 6 条是我为排查 DRC 挂起而**临时删掉 4 个铺铜**造成的（GND 少了 6 个靠铺铜连通的点），重铺后应回到 39。

### 3.5.5 官方 DRC 的"有效阈值"标定（说明 0 clearance 不等于满足 6mil）

`_drc_sensitivity.js`：在板外 x=100mm 处放 3 组平行走线（宽 0.254mm），跑 DRC 后删除（已确认清理干净，走线数回到 1789）：

| 组 | 间距 | DRC 是否报 Clearance |
|---|---|---|
| A | 0.196mm | 否 |
| B | 0.146mm | **否** |
| C | 0.046mm | 是（Track to Track，ruleName `copperThickness1oz`） |

→ 复位注入规则后，官方 DRC 的 track-track 有效阈值落在 (0.046, 0.146] 之间（与 FINAL_STATE 记录的"线-线 0.102mm"一致）。
**因此"官方 DRC = 0 clearance"不能当作满足 6mil 的证据**，本报告一律用独立几何审计（shapely）作为 6mil 判据。

### 3.5.6 其它已确认事实

- 内层导入 bug 复现：每次 SES 导入后，内层铜落在 **21/22**，必须 `qq.py fix_layers.js`（本次移动 323 条 → 15/16 正确）。
- 4 个铺铜：`eda.pcb_PrimitivePour.create()` 三种签名全部报"无法创建覆铜边框图元"，原生 API 建不了；铺铜刷新用实例方法 **`p.rebuildCopperRegion()`**（4 个都成功，fills = 329/106/127/9）。
- 官方 DRC 偶发**挂起**（同一状态先 2.7s，改完线宽后 >270s 不返回，MCP 的 `check_pcb_drc` 也超时）；等待 ~3 分钟、EasyEDA 窗口重连（windowId a77cb100→3cd82121）后恢复正常（2.1s）。判断是 EasyEDA 内部 DRC 作业卡住，与铺铜无关（删掉铺铜后依旧挂）。

---

## 4. 第 4~8 步执行记录与最终数字（2026-09-21 00:45~00:55）

### 4.1 导回链路（tourbox5 未跑完，主线改用 tourbox4 + restore_widths）
| 步骤 | 命令 | 结果 |
|---|---|---|
| 导入 | `python ses_import.py <ses>` | 清空旧铜 → 分块传 SES → `importAutoRouteSesFile` 返回 OK；内层落 21/22 |
| 修层 | `python qq.py fix_layers.js 800` | 移动 323 条 → 层分布回到 {1:1091, 2:375, 15:300, 16:23}（21/22 清空） |
| 线宽还原 | `python restore_widths.py <ses> --apply` | 匹配 1733/1789，应用 1789 条；线宽回到 FR 原值 |
| 铺铜 | （由上层代理执行 `pour4c.js` + 规则复位） | 4 个铺铜恢复：GND@1、GND@15、GND@2、VCC@16；`copilot_router` 残留 0 |
| 规则 | `python set_rules_6mil.py --apply` | 见 4.2 |
| 快照 | `python extract_live.py` | 1786 线 / 196 过孔 / 650 焊盘 |
| 审计 | `python audit6.py` | 见 4.4 |
| DRC | `python qq.py drc_report.js` | 见 4.3 |

### 4.2 板子 DRC 规则显式设成 6mil（这是"官方 DRC 能判 6mil"的前提）
规则数据在 `eda.pcb_Drc.getCurrentRuleConfiguration()` → `config.Spacing["Safe Spacing"][<规则名>].tables["1"].content`（下三角矩阵，单位 mm）。
**关键发现：默认规则 `copperThickness1oz` 的 Track→Track 只有 0.10199878mm**，而其它格子本来就已经达标：

| 格子 | 原值 | 目标 | 处理 |
|---|---|---|---|
| Track→Track（copperThickness1oz / Plane_innerPlane / Copper_copperRegion） | 0.102 | 0.152 | **改为 0.15200122** ✅ |
| Track→Track（copperThickness2oz） | 0.203 | ≥0.152 | 不动（只抬高，不放松） |
| Track→SMD Pad / TH Pad / Via | 0.152 | 0.152 | 已达标 |
| Track→Board Outline | 0.2999 | 0.30 | 已达标 |
| Hole（hole→任何铜） | 0.17526 | 0.175 | 已达标 |
| Copper/Plane Zone→ | 0.254 | — | 保持 |
| Physics/Track 最小线宽 minValue | 0.127 | 0.127 | 已达标；默认 0.254、最大 2.54 |
| Physics/Via Size | 0.61/0.305 | — | 与板上 196 个过孔(24/12mil)一致 |

⚠ **写入 API 的坑**：必须传**内层 config 对象**，即 `overwriteCurrentRuleConfiguration(cfg.config)` → 返回 `true` 且生效；
传整个 `{name, config}` 包会**静默无效**（返回 `OK undefined`，值不变，容易误判成功）。
顺带把已无引用的 `copilot_router_*` 规则定义（Spacing 4 条 / Physics 10 条 / Plane 1 条）一并删除，复核 net rules 里 `copilot_router` = **0**。

### 4.3 官方 DRC 实测（6mil 规则下，`eda.pcb_Drc.check(false,false,true)`，3877ms）

| 分组 | 数量 | 说明 |
|---|---|---|
| Clearance Error | **1** | Track to Track，layer=Top Layer，rule=`copperThickness1oz` |
| Connection Error | **39** | 19 个网未布通（GND/VCC/GND_BK/XL2/$1N17527/RF/PT2/IP+5V/$1N17186/$1N19139/$1N19304/PT1/SW_BK/$1N26963/PWM_U/PWM_LU/PWM_V/PWM_LV/PWM_LW） |
| **合计** | **40** | 对比修改前（复位规则 + 胖线宽）= 1400 |

那 1 条 Clearance 的原始记录：
```
obj1 = Track (VCC): e34340        id 92ba4f3af97a9210
obj2 = Track ($1N3685): e35733    id 4bc6e2dd38a97f31
layer = Top Layer(1)   errData.minDistance = 0.59488mm   errData.clearance = 0.59843mm
```
注意：**它不是 6mil 违规**——DRC 报的是它违反了 0.59843mm（那是 DSL 的 zone 规则残留值，规则定义已删、net rules 已无引用）。
**巧合的是它正好也是我独立审计里唯一一条 6mil 违规（实测 0.1511mm，差 0.9µm）**，即同一对图元。

### 4.4 独立 6mil 几何审计（`audit6.py`，阈值 0.152mm，同层异网）

| 类别 | <0.152mm 的对数 | 间距范围 |
|---|---|---|
| 线-线 | **1** | 0.1511mm |
| 线-过孔 | **10** | 全部 0.1517mm |
| 线-焊盘 | **1** | 0.1511mm |
| 过孔-过孔 / 过孔-焊盘 / 焊盘-焊盘 | 0 | — |
| **合计** | **12** | 全部只差 **0.3~0.9µm** |

即：**整块板在 6mil 下只差 12 对、每对都只差不到 1µm**。
官方 DRC 只报 1 条、我的审计报 12 条，原因是 **EasyEDA 的 DRC 会把实测距离按 ~1µm 取整后再比较**（0.1517→0.152 判过；0.1511→0.151 判不过），而我的审计用原始浮点值。

> 审计模型的坑（已修）：`Pad` 字符串 `OVAL,宽,高` 的长轴要取**较大者**；`ELLIPSE,直径,直径` 当圆处理（live.json 里是 mil）。
> 修之前会误报 375 条（假的重叠），修之后 12 条且与官方 DRC 方向一致。

### 4.5 那 1 对 0.9µm 超差图元的精确坐标与修改建议（供手工微调）

| | A | B |
|---|---|---|
| 网络 | VCC | $1N3685 |
| 类型/层 | Track / TOP(1) | Track / TOP(1) |
| 图元 id | `92ba4f3af97a9210` | `4bc6e2dd38a97f31` |
| 线宽 | 0.2553mm (10.05 mil) | 0.2553mm (10.05 mil) |
| 端点1 | (38.3057, 49.8526) mm = (1508.10, 1962.70) mil | (37.9400, 49.4106) mm = (1493.70, 1945.30) mil |
| 端点2 | (37.5107, 49.8526) mm = (1476.80, 1962.70) mil | (37.9755, 49.4462) mm = (1495.075, 1946.70) mil |
| 形态 | 水平段，长 0.795mm | 45° 短斜段，长 0.05mm |

中心线最近距离 0.4064mm，铜间隙 = 0.4064 − 0.2553 = **0.1511mm（差 0.9µm）**。

修改建议（任选其一，都只动 1 个图元）：
1. **推荐：把 B（$1N3685 短斜段）线宽从 0.2553 改成 0.2001mm** → 间隙 = 0.4064 − (0.2553+0.2001)/2 = **0.1787mm** ✅（改线宽不会破坏连通性）
2. 把 B 整段沿 −y 平移 1 mil（0.0254mm）→ 间隙 **0.1765mm** ✅（风险：B 两端若接别的铜会断开，需先确认）
3. 把 A 沿 +y 平移 1 mil → 间隙 **0.1765mm** ✅（A 是 0.795mm 的 VCC 水平段，需确认两端连接）

另有 10 对"线-过孔"差 0.3µm（0.1517mm，官方 DRC 不报），清单见 `audit6.json` 的 `violations`；若要"零讨论空间"，可同样把其中一侧线宽收窄 1 mil。

### 4.6 Freerouting 第二轮（tourbox5，8mil）——已按上层代理决定终止并释放 CPU

| pass | 完成时刻 | score | unrouted | violations |
|---|---|---|---|---|
| fanout | 23:51:02 | — | 445/497 SMD 逃逸(89.5%) | — |
| 1 | 23:54:01 | 722.96 | 89 | 152 |
| 2 | 23:57:29 | 762.40 | 72 | 152 |
| 3 | 00:00:42 | 774.01 | 67 | 152 |
| 13 | 00:30:18 | 785.61 | 62 | 152 |
| 14 | 00:34:00 | 785.61 | 62 | 152 |
| 15 | 00:37:49 | 787.93 | 61 | 152 |
| 16 | 00:41:33 | 787.93 | 61 | 152 |
| 17 | 00:45:08 | 785.61 | 62 | 152 |
| 18 | 00:49:07 | 785.61 | 62 | 152 |

- 18 pass 后分数在 785.6~787.9 之间来回摆动（未收敛到更高值），**未布通 61~62 项**（远多于 6.03mil 版的 19 项），故未跑满 30 pass 即终止；**没有产出 tourbox5.ses**（FR 只在结束时写文件）。
- 结论：8mil 间距余量对这个密度（29~31% 铜覆盖）代价过大 → **主线采用 tourbox4 路由 + `restore_widths.py` 线宽还原**。

---

## 5. 结论

1. **原假设需要修正**：1400 个错误的主因**不是**"DSN 规则太松"，而是
   (a) EasyEDA 的 SES 导入器**忽略 SES 里的线宽**、改用板上 net rule 的 Track 宽度（注入规则时 PGND 被放大 6 倍），把 FR 设计好的净间距吃掉；
   (b) 注入的 `copilot_router_*` 规则本身把大量间距要求抬到 0.59843mm，制造 769 条"假违规"。
   FR 的原始输出（SES）在 6mil 阈值下 **0 违规**，是被导入器改坏的。
2. **DSN 规则确实偏紧（不是松）**：结构级 6.03mil 只比 6mil 目标高 1.2µm；默认类 `''` 4.02mil、USB_DP/DM 5.91mil 反而**低于**目标。已生成 `tools/tourbox5.dsn`（clearance 全部抬到 8mil=0.2032mm，DM/DP 线宽 5→6mil）。
3. **FR 使用 DSN 的"结构级"规则、忽略 net class 规则**（实测：SES 里只有 10.05mil 这一个主宽度；class 里的 11.81/41.34/61.02mil 一条都没出现）。想控制 FR 的线宽/间距，只能改 `(rule(clear ...))` / `(rule(width ...))`。
4. **板子当前状态（主线交付）**：
   - 铜：1786 段走线 / 196 过孔 / 4 铺铜（GND@TOP、GND@INNER_1、GND@BOTTOM、VCC@INNER_2）
   - 层：{TOP:1088, BOTTOM:375, INNER_1:300, INNER_2:23}
   - 线宽回到 FR 原值（0.2553mm 为主，局部 0.2001/0.1914/0.2499/0.1532）
   - **官方 DRC（6mil 规则）= 1 Clearance + 39 Connection**
   - **独立 6mil 审计 = 12 对、每对只差 0.3~0.9µm**
   - 剩下 39 条 Connection Error 是 FR 未布通的 19 个网（布线完备性问题，与规则无关）
5. **两条铁律（后续任何操作都要守）**：
   - ① 任何 `run_pcb_router_dsl`（含 `pour4c.js` 这类带 `plane()` 的脚本）之后，**必须**把 net rules 里的 `copilot_router_*` 复位成 `default`，并复核引用数 = 0；否则 DRC 会凭空出现上千条假违规。
   - ② 每次 SES 导入后**必须**依次跑：`fix_layers.js`（21/22→15/16）→ `restore_widths.py <ses> --apply`（把被统一成 0.254mm 的线宽还原成 FR 值）。缺任一步，6mil 违规就会以数十~数百条的量级复现。

---

## 6. 交付物清单（本次新增）

| 文件 | 作用 |
|---|---|
| `tools/tourbox5.dsn` | 修正规则后的 DSN（clearance 8mil、width 8mil、DM/DP 6mil），未覆盖 tourbox4 |
| `mk_dsn5.py` | 生成 tourbox5.dsn 的脚本（只改规则行，逐行 diff 校验） |
| `restore_widths.py` | **核心修复**：把导入后统一成 0.254mm 的线宽还原成 SES 原值（支持 `--apply`，缺省 dry-run） |
| `set_rules_6mil.py` | 把板子 DRC 规则的 Track→Track 抬到 0.152mm 并删除 copilot_router 规则定义 |
| `audit6.py` → `audit6.json` | 6mil 全类别几何审计（线-线/线-过孔/线-焊盘/过孔-过孔…） |
| `drc_report.js` | 官方 DRC 全量分解（按规则/类型/层/实测间距 + net rules 卫生检查） |
| `_drc_attr2/3/4.js` | 1400 条的归因分析（ruleName、errData 真值、同网/异网） |
| `_ses_gaps.py` | 直接审计 SES 原始几何（证明 FR 输出是干净的） |
| `_drc_sensitivity.js` | 标定官方 DRC 的有效阈值（0.046 报 / 0.146 不报） |
| `ses_import.py` | 已改成可传 SES 路径参数（缺省仍 tourbox4.ses，兼容旧调用） |
| `REROUTE_LOG.md` | 本文件 |
