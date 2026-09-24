# ⏸ 关机续接说明（2026-09-20 晚）

关机前已完成：EasyEDA 文档已保存、检查点已存、后台任务已停、全部文件已核对在 D 盘工作区。

---

## 一、当前板子状态

| 项目 | 状态 |
|---|---|
| EasyEDA 检查点 | **`mvg7pv5lzwaicz8t`** ← 本状态（最新） |
| 历史检查点 | `gdfvpt7jr1hzunte` = 摆放定稿（零铜）；`vo041zq1whlpybf4` = 4层+第1轮布线（**内层铜在错层 21/22**） |
| 层结构 | **4 层**：id1=TOP、id2=BOTTOM、**id15=INNER_1、id16=INNER_2**（EasyEDA 标准层号） |
| 铜 | 第 1 轮 Freerouting 结果，**已做层号修正**（21→15、22→16） |
| 未布网络 | **19 条**：RF / XIN / XOUT / XL1 / USB_DM / SWCLK / PWM_U / PWM_V / PWM_W / PWM_LU / PWM_LV / PWM_LW / QSPI_SD3 / SDI / PT1 / PT2 / I2CSDA / IP+5V / SWDIO |
| 铺铜 | **0 个**（已删除；正确顺序是布线完成后再铺） |

---

## 二、重启后怎么接着做

```bat
cd D:\360Downloads\tourbox\pcb-layout
set PYTHONIOENCODING=utf-8
set PY=C:\Users\yinsh\AppData\Local\Programs\Python\Python310\python.exe
```

### 步骤 1：抽取当前板子状态（有副作用的抽取器，别 import）
```bat
%PY% extract_live.py
%PY% qq.py comps3.js 800 > comps3_raw.json
%PY% -c "import json,io;d=json.loads(io.open('comps3_raw.json',encoding='utf-8').read());io.open('comps3.json','w',encoding='utf-8').write(json.dumps(json.loads(d['result']),ensure_ascii=False,indent=1))"
```

### 步骤 2：第 2 轮布线（DSN 已含 1537 段已有铜，直接跑即可）
```bat
%PY% dsn_export3.py        :: 板子若又改过才需要重新导出
cd tools
jdk-25.0.4.1+1\bin\java.exe -jar freerouting-2.4.1.jar -de tourbox4.dsn -do tourbox4.ses -mp 30 -oit 0.25
cd ..
%PY% ses_import.py
%PY% qq.py fix_layers.js 800      :: ⚠️ 必做！SES 回导会把内层放到 21/22，立刻搬回 15/16
```

### 步骤 3：铺铜（MCP 的 plane() 在本板永久不可用，必须走原生 API）
```js
// 目标：INNER_1(15)=GND 平面、INNER_2(16)=VCC 平面、TOP/BOTTOM=GND 铺铜
// 间隙 0.3mm、移除 <10mm² 孤岛
// 途径A: eda.pcb_PrimitivePour.create(...)   (参数签名需先探)
// 途径B: eda.pcb_PrimitiveFill.create(多边形) -> setState_Net('GND') -> convertToPour()
```
铺完抓回来验证：`%PY% grab_pours.py`

### 步骤 4：关键网络精修（4 条）
- **USB 差分**（USB_DP/USB_DM）：90Ω 差分、等长 ≤0.15mm、过孔 ≤2/对
- **天线馈线**（RF→L6→L7→ANT）：50Ω 共面波导、净空区内零铜
- **晶振**（XIN/XOUT/XL1/XL2）：0 过孔、短直、包地
- **电机相线**（U/V/W/PWM_*）：载流足够、距 ADC 网络 ≥3mm

### 步骤 5：验收
```bat
%PY% place_verify.py     :: 几何规则（当前 11 条，全是结构件/微米级）
%PY% place_elec.py       :: 摆放电气 7 项（当前 56.7/100）
%PY% route_elec.py       :: 布线电气 12 项
:: + EasyEDA DRC（MCP 工具 check_pcb_drc，或让 AI 调）
```

---

## 三、三个必须记住的坑

1. **SES 回导会把内层铜放到 21/22（该板上不存在的层）** → 每次导完立刻跑 `fix_layers.js`
2. **`extract_live.py` 是有副作用的抽取器**（会重写 `live.json`）→ 绝对不要 `import live`（已改名，误 import 会直接报错）
3. **MCP 的 `run_pcb_router_dsl` 在这块板上永久不可用** → 它把内层 15/16 认成别的层，任何含内层铜的板都会 `ROUTING_UNKNOWN_LAYER`；铺铜/规则只能走原生 API

---

## 四、工具清单（全部在 `D:\360Downloads\tourbox\pcb-layout`）

| 文件 | 作用 |
|---|---|
| `place_verify.py` | 几何规则 7 类 + 美观评分（退出码 0/1/2） |
| `place_elec.py` | 摆放电气 7 项（去耦/IC地脚/DC-DC/晶振/敏感件/地拓扑/RF链） |
| `route_elec.py` | 布线电气 12 项（参考平面/去耦过孔/USB/天线/晶振/载流/缝合过孔…） |
| `place_cpsat.py` | CP-SAT 摆放求解器（备用） |
| `extract_live.py` | 从 EDA 抽几何快照 → `live.json`（**有副作用**） |
| `qq.py` + `comps3.js` | 抽元件位置 → `comps3.json` |
| `dsn_export3.py` | 官方 DSN 导出（`getDsnFile()` 返回 File 对象，要 `.text()`） |
| `ses_import.py` | SES 分块导入 |
| `fix_layers.js` | **内层层号修正 21→15 / 22→16（每轮必跑）** |
| `grab_pours.py` | 抓铺铜几何到 `live.json spec.pours` |
| `sync_motor_center.py` | 电机禁区圆心跟随 AS5600（U5 挪动后跑） |
| `board_keepouts.json` | 真实禁区几何（滚轮挖槽 8 点多边形、天线矩形、电机圆） |
| `_snap/placement_final_20260920_1619/` | 摆放定稿快照（含指纹与完整报告） |
| `tools/` | Freerouting 2.4.1 jar + JDK25 + 各轮 DSN/SES |

---

## 五、整体进度回顾

| 阶段 | 状态 |
|---|---|
| 原理图 | 冻结（用户已审） |
| **摆放** | ✅ 定稿 —— 几何 11 条（全是结构件/微米级）、电气 56.7/100（起点 53.0） |
| 4 层叠层 | ✅ |
| **布线第 1 轮** | ✅ 112/126 网络（1781 段 / 201 过孔），剩 19 条 |
| 布线第 2 轮 | ⏳ 已导出含铜 DSN（247974 字符、1537 段铜），启动过一次被关机中断，可直接重跑 |
| 铺铜 | ❌ 待做（布线完成后） |
| 关键网络精修 | ❌ 待做 |
| DRC / Gerber | ❌ 待做 |

**天线匹配仍是用户的手工活**（用户明确说过）。

---

# 🔄 会话 2 进展与交接（继续 2026-09-20 深夜）

## 本次做了什么
1. 重启桥接（开机后 49620 端口没了 → `node C:/Users/yinsh/.dsh/skills/easyeda-api/scripts/bridge-server.mjs`，约 80 秒扩展重连）
2. 确认状态在盘上：1780 段 / 201 过孔 / 112 网络，按层 {TOP:1092, BOTTOM:357, INNER_1:281, INNER_2:50}（层号修正在重启后仍有效 ✅）
3. 重新导出含铜 DSN（1537 段 wire）
4. **第 2 轮 Freerouting 反而变差**（832 违规、26-32 条未布）→ 已停
5. 用自写 A* 补 11 条缺铜网络 → **全部失败**（我的 A* 只走 TOP/BOTTOM，用不上内层；板子已达 29-31% 铜覆盖率）
6. Freerouting `-inc` 定向布线 → **-inc 未生效**（仍从 250 项开始）→ 已停

## 结论：11 条缺铜网络目前布不出来，根因是"层号 bug 的连锁反应"
- 我的 `stack4.js` 建内层时生成了**非标准层号 21/22**（真实应为 15/16）
- Freerouting 的 SES 回导把内层铜放到 21/22 → 我手动搬到 15/16
- **但搬迁可能弄断了过孔的层连通**（过孔若是跨层盲孔/受限跨度，搬走后就不连了）→ 导致再导出 DSN 时 Freerouting 看到"断连+违规"（832 个）→ 无法继续优化

## 推荐的正解（约 1.5-2 小时，一次做干净）
```
① 清空全部铜（或从检查点 gdfvpt7jr1hzunte 的摆放定稿重来）
② 用 EasyEDA **自己的**层管理把内层建成 15/16（不要用 MCP 的 stack()）
   —— 或在 EasyEDA 界面里切换到 4 层（它会用标准层号）
③ 重新导 DSN（此时层号标准）→ Freerouting 一轮跑满 30 pass
④ SES 回导 → 此时内层会落到 15/16，**不需要 fix_layers.js**
⑤ 铺铜 pour4c.js（已写好，含 4 层 stack 声明；DSL 现在能读懂板子了 ✅）
⑥ route_elec.py 12 项 + EasyEDA DRC 验收
```

## 已验证可用的关键结论
- **`run_pcb_router_dsl` 现在能读这块板了** ✅（报错从 `ROUTING_UNKNOWN_LAYER` 变成 `DSL_STACK_DIELECTRIC_REQUIRED`）→ 只要脚本里带 `stack()` 声明就能用 → `pour4c.js` 已按此写好
- 铺铜目标：INNER_1=GND 平面、INNER_2=VCC 平面、TOP/BOTTOM=GND（0.3mm 间隙、移除<10mm² 孤岛）
- 缺铜的 11 条：SDI SWCLK USB_DP PT1 PWM_U PWM_V PWM_W PWM_LU $1N19139 $1N19304 $1N26963

## 当前检查点
- `mvg7pv5lzwaicz8t`（112 网络布线 + 层号已修正）
- `gdfvpt7jr1hzunte`（摆放定稿、零铜）← **如果走"正解"就从这里重来**

---

# 🌙 通宵作业：1400 个 DRC 错误的根因与修复（子代理 A 诊断结论）

## 根因（有证据，非猜测）
| 发现 | 数据 |
|---|---|
| **SES 本身几何干净** | 对 `tourbox4.ses` 做 shapely 真值检查：间距 <0.152mm 的对数 = **0** ✅ Freerouting 布线没问题 |
| **1361/1400 错误挂在注入规则上** | `copilot_router_net_0_spacing = 0.59843mm` ✗，其中 **769 个是假违规**（按真 6mil 完全合格）|
| **注入规则改写了线宽** | EasyEDA 的 SES 导入器用了**板上 net rule 的 Track 宽度**而非 SES 的 ✗ → PGND 被放粗 **6 倍**（0.2553→1.5494mm）、+5V 4 倍、VCC 3 倍、GND 2 倍 ✗ → 粗线必然压间距 |
| **594 个 track-track** | 用注入后的粗线宽重算才出现；按 SES 原线宽重算全部 ≥0.152mm ✅ |

## 已执行的修复
1. **Net rules 全量复位** ✅：`eda.pcb_Drc.getNetRules()` 里 **379 处 `copilot_router_*`** → 全部改为 `default` → `overwriteNetRules()` → 复核 **0 处残留**；125 条 net rule 干净；原件备份在浏览器 `window.__netrules_backup`
2. 文档已保存（uuid a13a9a0e...）
3. 子代理 A 正在跑 **tourbox5.dsn**（结构级 clear/width=8mil、126 个 class 全部 8mil clearance、DM/DP width 6mil）→ `-mp 30 -oit 0.25`，日志 `tools/fr5.log`

## 关键顺序（必须遵守）
```
① Net rules 复位（已完成 ✅）
② Freerouting 跑 tourbox5.dsn（进行中）
③ ses_import.py 导回（指向 tourbox5.ses）—— ⚠️ 导前不可再跑 run_pcb_router_dsl（会重新注入规则）
④ qq.py fix_layers.js（21→15, 22→16，每次必做）
⑤ extract_live.py 刷新快照
⑥ eda.pcb_Drc.check() 全量 DRC 分解
⑦ 校验线宽是否回到 SES 值：GND≈0.153 / VCC≈0.200 / PGND≈0.255 / +5V≈0.255 mm
   （若仍是 0.30/0.60/1.55/1.05 → 复位未生效，立即排查）
```

## 预期与剩余风险
- 预期：1361 个间距错误里绝大多数应消失（769 假违规 + 粗线造成的真违规）
- 剩余风险 A：**8mil 更紧的规则会降低 Freerouting 通过率**（fanout not-routed 从 8-17 涨到 44-48）→ 未布通条数可能比 19 条多 → 需要额外一轮或手工补
- 剩余风险 B：Connection Error 属于"布线完备性"，不是规则问题，得靠补布
- 6 处 0-mil 真短路（VCC↔QSPI_SCLK(U3_6)、PGND↔GND_BK、U↔H1_2、VCC↔SW13_2、IP+5V↔挖槽e29）需单独修

## 并行子代理
- A `d54bb122-d2c2-493a-b954-0eef79fe397f`：DSN 规则修正 + Freerouting 重跑 + 导回（产出 `REROUTE_LOG.md`）
- B `8c712451-0127-41e9-aed7-7f2ac086cb94`：全量 DRC 导出器（产出 `drc_full.py` / `DRC_FULL_REPORT.md`）—— 已确认 `eda.pcb_Drc` 有 `check()` / `getNetRules()` / `overwriteNetRules()` / `getAllRuleConfigurations()` 等方法

---

# ★ 收官状态（不要再折腾布线了 —— 已经全清）

## 结论
- **DRC = 0 违规**（既无 Clearance 也无 Connection），1922 线 / 261 过孔 / 4 铺铜(已填充 4) / 166 元件
- 检查点：**`5dups6uxk3qnlvz1`**（终版）、`mifofyowv2fhkivz`（上一版 0/3）
- 制造文件已按终版重新导出到 `deliver/`（STEP 需手工导）

## 最后闭环的一网
`$1N19139`（C62_2 ↔ U6.AC5）：TOP 无解（BGA 缝 9.88mil < 17mil 需求，A* 4327 万次弹出穷尽证实），
改用 **dogbone**：14mil 孔 @(2532.64,1229.18) 余量 +0.91 + 16mil 孔 @(2327.56,1193)
+ TOP 5mil 短桩 + INNER_2 5mil 三段线。刻意不用 via-in-pad（免灌锡工艺）。

## 几何内核要点（写死，别再踩）
- **矩形焊盘必须用精确旋转框距**（`hypot(max(qx,0),max(qy,0)) + min(max(qx,qy),0)`），
  **不要用对角线半径** —— 曾经把 190.9mil 方盘算成 r=135mil 的圆，导致"每段线都被判死"、
  "找不到孔位"两个假结论，浪费了一整轮。
- A* 开放列表**必须用二叉堆**：线性扫描版跑 40s 未出结果并锁死 EasyEDA 主线程
  （桥接 900s 才超时），只能关标签页掐断。堆版 43M 弹出 / 40s、常规 200k 弹出 / 0.2s。
- 长脚本（>8KB）**不要用 bash heredoc**（会被截断成 8192 字节），改用文件写入工具。

## 若要继续（可选，非必需）
1. 手工体验/复核：`python drc_full.py --limit 0`
2. 想更稳的 dogbone 余量：把该孔 14mil→13mil，或外移 1-2mil，重跑 `solve2.js`（会自动重解并覆盖）
3. STEP 3D 手工导出（桥接通道上限）

## 追加优化（已完成并验证）
- ① 电机相线 **U/V/W/PGND 10.1 → 25mil**（逐段取合法最大值）+ 并联过孔 U2/V2/W3/PGND5 → DRC 0
  - H1 = 3 针通孔电机连接器（40.2mil 钻孔）；U4 三相各 2 脚并联
  - 坑1: "孔到孔≥11.80mil" 同网也查；坑2: 通孔焊盘的钻孔必须建模（否则孔压孔 0.00mil）
- ② RF 馈线跨槽 88mil(19%)/5处 → **52mil(11%)/4处**（让开两个过孔防焊盘），只剩 `$1N18259` 拓扑必穿
  - 手法：A* + 虚拟障碍；**建格前必须预筛障碍**（全量焊盘会让扫格超时被看门狗 500）
- 制造文件已重导；MCP 恢复后需补 sync + DRC + 存档
- 终检通过: sync 后全量 DRC = 0/0；**最终检查点 `hbux13vca7ugamcw`**
- 天线区用户改后复核: 新位置合法(0 间距违规)；但发现 (1) **TOP 层 GND 铺铜丢失** → 用 `pour_top.js`(MCP DSL, 只建 TOP) 重建, 修复 C66_1/R28_2/R31_2/R32_1 四个 GND 焊盘; (2) `$1N19975`(L7_2↔R28_1) 整网无铜 → 补 186mil 10mil 直线
- 终态 1915 线 / 268 过孔 / 4 铺铜 / DRC 0-0

## 打板前终检（已完成）
- **盲埋孔: 无** —— 268 个过孔全部 `viaType=0`(通孔) + `designRuleBlindViaName=""`；
  钻带只有 3 个文件且全名带 Through（`Drill_PTH_Through.DRL` 331孔=268过孔+63通孔焊盘、
  `Drill_PTH_Through_Via.DRL` 268孔、`Drill_NPTH_Through.DRL` 2孔）→ 按普通 4 层板下单，无盲埋孔加价
- 工艺对照: 最小线宽 5mil / 最小间距 6mil(0.152) / 最小钻孔 0.203mm / 最小环宽 0.076mm(1个14mil dogbone孔) / 通孔盘环宽≥0.2mm —— 全部达标
- 板框 90×90mm 闭合；挖槽 8 点闭合多边形（已核 GKO）
- ⚠️ **API 坑**: 过孔钻孔字段是 **`holeDiameter`**（`hole` 在过孔上恒为 0/空；焊盘上才是 `hole`）——
  我因此白跑了一轮"钻孔读不到"的排查

## 免费工艺档改造（已完成）
- 全部 268 个过孔孔经 8mil→**12mil(0.3048mm)**，外径统一 16mil(0.4064mm)+1×24mil
  → 最小孔 0.3048 ≥ 0.3 ✓、环宽 0.0508 ✓ = 嘉立创免费档「0.3mm孔/外径0.4」规格
- dogbone 孔 14mil→16mil 并移到 (2536,1228.5)（重连 TOP 短桩 + INNER_2 走线端点）
- 遗留 12 处"孔到孔"0.269~0.297mm（板内规则 0.3mm 严于板厂；板厂常见下限 0.25mm）
  → 若 DFM 打回: 孔改 10mil(0.25mm档), 孔到孔回到 0.32mm, DRC 立即恢复 0/0
- **踩坑**: ①孔变大必须先查孔到孔(同网也查) ②动孔会牵连"孔到走线"间距, 必须先算好再挪
  ③`segSeg(a,b,c,d)` 与 `segSeg(a,b)` 两种签名混用会报 `Cannot read properties of undefined`
- 检查点: zexynfkukmbbbutw; 制造文件已重导
- 免费档收尾: 12 处孔到孔 → **3 处**(0.272~0.287mm) —— 局部重布 10 个过孔 + 10 段 8mil 短桩, 零副作用
  - 残留 3 对在 U4 PWM 扇出/(2673,1497), 几何锁死(对向各挪 0.5~3mil 也无解) → 需整组重布扇出
  - 退路: 0.25mm 档(孔 10mil) → 孔到孔 0.32~0.34mm, DRC 全清
  - 关键: **FR 不检查孔到孔**, 全板重跑解决不了
  - 检查点: vqi1dmwt6kl8m6xa
