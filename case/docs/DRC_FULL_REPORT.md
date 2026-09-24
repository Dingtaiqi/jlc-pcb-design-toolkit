# DRC 全量导出报告 — tourbox eltie (EasyEDA Pro 4 层板)

* PCB uuid：`a13a9a0e834c40d3a24ee99ae8ff4e1c`
* 桥接：`http://localhost:49620/execute`（`node C:/Users/yinsh/.dsh/skills/easyeda-api/scripts/bridge-server.mjs`）
* 脚本：`drc_full.py`（全量导出器）、`drc_to_commands.py`（违规 → 修复动作清单）
* 全程只读：只调用 `eda.pcb_Drc.check(...)` 与 `getAll()/getState_*()/getCopperRegion()/getNetRules()`；
  未修改任何板子对象、未写入 `live.json`/`comps3.json`、未 `import live`
  （两个脚本里 **0 处** 引用 `live.json`/`comps3.json`，写文件只发生在显式给出的
  `--json/--out/--tsv` 路径；`live.json` 在 00:44:52 的更新来自本会话之外的 extractor，不是本工具链）

---

## 1. 探测到的 DRC API 清单

### 1.1 入口方法

| 位置 | 方法 | 状态 | 说明 |
|---|---|---|---|
| `eda.pcb_Drc` | `check(strict, userInterface, includeVerboseError)` | ✅ **可用，全量** | 唯一能跑完整 DRC 并返回全部违规的入口 |
| `eda.pcb_Drc` | `startRealTimeDrc()` | ❌ 不可用 | 源码是空实现 `startRealTimeDrc(){return!1}` |
| `eda.pcb_Drc` | `getRealTimeDrcStatus()` | ❌ 不可用 | 同样是空实现，恒返回 `false` |
| `eda.pcb_Drc` | `stopRealTimeDrc()` | ❌ 不可用 | 空实现 |
| `eda.pcb_Document` | —（20 个方法） | — | **没有**任何 DRC 入口（只有 save/clearRouting/importSesFile/getPrimitivesInRegion…） |
| `eda.sch_Drc` | `check(...)` | — | 原理图 DRC，与 PCB 无关 |
| `eda.*` 全量扫描 | `/drc/i` 命中 | — | 只有 `pcb_Drc` 与 `sch_Drc`；**不存在** `getAll/run/getDRCResult/getDrcResult` 之类方法 |

`eda.pcb_Drc` 原型方法全清单（`Object.getOwnPropertyNames(Object.getPrototypeOf(eda.pcb_Drc))`，45 项）：

```
constructor, check, getRealTimeDrcStatus, startRealTimeDrc, stopRealTimeDrc,
getCurrentRuleConfigurationName, getCurrentRuleConfiguration, getRuleConfiguration,
getAllRuleConfigurations, saveRuleConfiguration, renameRuleConfiguration,
deleteRuleConfiguration, getDefaultRuleConfigurationName, setAsDefaultRuleConfiguration,
overwriteCurrentRuleConfiguration, getNetRules, overwriteNetRules, getNetByNetRules,
overwriteNetByNetRules, getRegionRules, overwriteRegionRules, createNetClass,
deleteNetClass, modifyNetClassName, addNetToNetClass, removeNetFromNetClass,
getAllNetClasses, createDifferentialPair, deleteDifferentialPair, modifyDifferentialPairName,
modifyDifferentialPairPositiveNet, modifyDifferentialPairNegativeNet, getAllDifferentialPairs,
createEqualLengthNetGroup, deleteEqualLengthNetGroup, modifyEqualLengthNetGroupName,
addNetToEqualLengthNetGroup, removeNetFromEqualLengthNetGroup, getAllEqualLengthNetGroups,
createPadPairGroup, deletePadPairGroup, modifyPadPairGroupName, addPadPairToPadPairGroup,
removePadPairFromPadPairGroup, getAllPadPairGroups, getPadPairGroupMinWireLength
```

`check` 的真实实现（`String(eda.pcb_Drc.check)`）：

```js
async check(t=!0, i=!1, n=!1){
  return await _.extensionApiMessageBus2.rpcCall("extensionApi.PCB_Drc.check",
         {strict:t, userInterface:i, includeVerboseError:n})
}
```

即：**默认 `strict=true`、`userInterface=false`、`includeVerboseError=false`**；
它是走扩展 RPC 到 DRC 引擎的，不是前端缓存的 UI 列表。
实测 `strict=true` 与 `strict=false` 在本板结果完全一致（同为 1400 / 同为 39），
所以本报告统一用 `check(false, false, true)`（verbose 才带 `objs[]` 真实图元 id）。

### 1.2 返回结构（三层）

```
[
  { name:"Clearance Error" | "Connection Error", count, visible, title,
    list: [                                   // 第 2 层：子类
      { name:"Track to Track" | "GND" | …, count, title, visible,
        list: [                               // 第 3 层：单条违规
          {
            visible, errorType, errorObjType, ruleName, ruleTypeName,
            obj1:{typeName,suffix}, obj2:{typeName,suffix},     // suffix 是显示用短 id（"e31890"），不能用于删除
            layer:"Inner1"/"Top Layer"/…,
            explanation:{
              str:"{obj1} to {obj2} distance is {minDistance}, should be {shouldBe}",
              param:{minDistance:"5.6mil", shouldBe:">= 6mil", type:"ClearanceError"},
              errData:{                          // ← 真实数据在这里
                globalIndex:"err5600", position:{x,y},
                obj1:"ddd0a4347fb5d1ed", obj1Type:"Track",         // 16 位十六进制真实图元 id
                obj2:"d6924e13d9d3acdb", obj2Type:"Track",
                minDistance:0.5594826817189125, clearance:0.59843,
                errorType:"Safe Spacing", layerIds:[15],
                obj1Suffix:"(GND): e31890", obj2Suffix:"(AGND): e32716",
                net:"…"(连接类才有), line:"…"(偶见)
              }
            },
            objs:["ddd0a4347fb5d1ed","d6924e13d9d3acdb"],   // 与 errData.obj1/obj2 同值，最适合消费
            globalIndex:"err5600", pos:{x,y}, parentId:"DRCTab|_|Errors|_|Clearance Error|_|Track to Track"
          }
        ]}
    ]}
]
```

* 连接类违规只有 1 个对象：`objs` 长度 1，另有 `net` / `isFree` 字段；
* 图元 id 形态：Track/Via = 16 位十六进制（`ddd0a4347fb5d1ed`）；Pad = 6~8 位（`e392e173`）；
  实测 **100% 能在 `getAll()` 图元里查到对应 id**（见 §4.4），可以安全用于自动修复。

### 1.3 是否“全量”：是（逐 pass 校验 `count == 实际条目数`）

每次调用都同时取 `group.count` 与展开后的实际条目数：

```
pass 0 :    39 条   declared=   39 一致
pass 1 :    39 条   declared=   39 一致
pass 2 :    39 条   declared=   39 一致
```

1400 条那次同样 `declared=1400 == items=1400`。
**没有任何抽样/截断**，所以不需要分页爆破；分块只发生在我自己的拉取路径上（见 §4.2）。

### 1.4 单位标定（重要，已交叉验证）

* **1 DRC internal unit = 0.254 mm = 10 mil**，即 `mm = raw × 0.254`、`mil = raw × 10`
* 对 `pos.x/pos.y` 与 `errData.minDistance/clearance` 同一尺度。
* 证据 1（文本 vs raw，1361 条 0 不一致）：
  `errData.minDistance=0.5594826817189125` → `×10 = 5.594 mil`，UI/param 文本写 `"5.6mil"`；
  `errData.clearance=0.59843` → `5.98 mil`，文本 `">= 6mil"`（0.1524 mm ✓）；
  旧规则集里 `param="0.006mm"` 对应 `raw=0.023661…` → `×0.254 = 0.00601 mm` ✓
* 证据 2（坐标 vs 板子）：本板 pos 原始范围 `x∈[12.97, 348.91]`，`×0.254 = 3.29 … 88.62 mm`，
  与元件 bbox（75…3450 mil = 1.9…87.6 mm）、~86×85 mm 的板框一致 ✓

### 1.5 一个真实踩坑：规则切换瞬间的“重复上报”

规则配置切换（`overwriteNetRules` 复位 `copilot_router_*`）过程中，我抓到过一次
`Clearance Error = 2722`，而稳定后是 `1361`：**恰好 2×1361**。
对页面缓存的取证证明：2722 条按“图元对/坐标”去重后正好是 1400
（`n_pairs=1400, dup_pairs=1361`，两次采样分别挂在 `copilot_router_net_0_spacing`
与另一套规则名下，几何/坐标完全相同）。

因此 `drc_full.py` 的做法是：**多次采样 + 按 `(类别,子类,图元id集合,suffix,layer,坐标)` 去重**，
同时保留 `copies_seen` / `rules_seen` / `passes` 三个字段，原始 per-pass 计数也照原样输出。

---

## 2. 真实总数与分类计数（三个快照）

| 快照 | 状态 | 规则 | 唯一违规点 | 唯一图元对 | Clearance | Connection |
|---|---|---|---|---|---|---|
| **A** `drc_full_before_reimport_recovered.json` | 导入前（1787 线 / 196 过孔 / 4 铺铜） | `copilot_router_net_0_spacing`（复位前，6 mil） | **1400** | 1400 | **1361** | **39** |
| **B** （仅计数，见 §2.2） | 复位后、导入前 | `自定义配置`（复位后） | **1204** | — | **1165** | **39** |
| **C** `drc_full_after_reimport.json` | SES 导入 + 重铺铜后（1786 线 / 196 过孔 / 4 铺铜已填充） | `自定义配置`（`copilot_router` 残留 0） | **40** | **39** | **0** | **40** |

### 2.1 快照 A（before，导入前，全量明细可用）

`1400` 条 = `Clearance Error 1361` + `Connection Error 39`（`pos` 3.29–88.62 mm，无缺坐标/缺 id）

| 类别 → 子类 | 精确计数 |
|---|---|
| Clearance Error / **Track to Track** | **594** |
| Clearance Error / **SMD Pad to Track** | **420** |
| Clearance Error / **Track to Via** | **231** |
| Clearance Error / **Hole to Track** | **71** |
| Clearance Error / **TH Pad to Track** | **40** |
| Clearance Error / **Slot Region to Track** | **5** |
| Connection Error / SMD Pad | 36 |
| Connection Error / TH Pad | 3 |

* 子类合计 8 个；间距实测值 531 条 = **0.00 mil（重叠/交叉）**，其余最大 5.94 mil，要求值 6 mil；
* 涉及网络 top：VCC 181、PGND 149、+5V 90、GND 90、V 74、W 61、U 59、1V1 29 …
* 规则名：`copilot_router_net_0_spacing` 1360 + `copilot_router_net_112_spacing` 1 + `Common` 39。
  → 这批违规是**路由器注入规则**下的产物。

### 2.2 快照 B（复位规则后、导入 SES 前，只有计数）

板子几何 `1787 线 / 196 过孔 / 4 铺铜(已填充) / 166 元件`，`net rules=125`，`copilot_router 残留=0`，
连续 2 次 DRC 完全一致：

| 类别 → 子类 | 计数 |
|---|---|
| Clearance Error / Track to Track | 393 |
| Clearance Error / SMD Pad to Track | 420 |
| Clearance Error / Track to Via | 231 |
| Clearance Error / Hole to Track | 76 |
| Clearance Error / TH Pad to Track | 40 |
| Clearance Error / Slot Region to Track | 5 |
| Connection Error / SMD Pad | 36 |
| Connection Error / TH Pad | 3 |
| **合计** | **1204** |

> 说明：这一版**没有留下逐条 JSON**——导出器第一版快照正好撞上 SES 导入清空布线
> （指纹变成 `0 线 / 0 过孔`，只剩 454 个连接错误），所以我改用 `--recover`
> 从页面缓存抢救了**规则复位前**的完整 1400 条（快照 A），并保留 B 的精确计数。
> 两个“导入前”口径的差值 `1400→1204` 全部来自规则复位（6mil→规则表默认）。

### 2.3 快照 C（after，当前板子，最终验收口径）

```
指纹        : 1786 线 / 196 过孔 / 4 铺铜(已填充 4) / 166 元件
规则配置    : 自定义配置 (net rules=125, copilot_router 残留=0)
per-pass    : 39 / 39 / 39  (declared == items，3 pass 完全一致)
唯一违规点  : 40        唯一图元对 : 39
分类        : Connection Error 40  (Clearance Error 0)
              ├─ SMD Pad 37
              └─ TH Pad  3
```

## 3. Before → After 对比（关键证据）

`python drc_full.py --diff drc_full_before_reimport_recovered.json` 的真实输出：

```
DRC 快照对比: drc_full_before_reimport_recovered.json  ->  now
  before: 1400 点    after: 40 点
  修复(消失): 1361    新增: 0    仍在: 39
修复(消失) 分类:
   Clearance Error / Track to Track           594
   Clearance Error / SMD Pad to Track         420
   Clearance Error / Track to Via             231
   Clearance Error / Hole to Track             71
   Clearance Error / TH Pad to Track           40
   Clearance Error / Slot Region to Track       5
新增 分类: (空)
仍在的违规: 39 条 Connection Error（几何无变化 → 与导入无关的既有孤岛网络）
```

**结论**：SES 重导入 + 规则复位把这 1361 个间隙违规全部清掉、且没有引入新的间隙违规；
剩下 39 个连接错误在导入前后**完全同签名**，属于独立的既有问题（见 §5）。

## 4. 覆盖率与自检

### 4.1 全量性
* 每个 pass 都校验 `group.count == 展开条目数` → 快照 A/C 均 100% 一致；
* 快照 C 三次连续采样 39/39/39（稳定），快照 A 三次采样 1400/…/1400；
* `strict` 开关不影响结果（都跑过），说明没有“更严格才能拿到”的隐藏集合。

### 4.2 分块拉取（避免桥接大响应 500）
DRC 结果先落在页面 `globalThis.__drcExport`，再按 150 条/次分块取回；
1400 条分 10 块、40 条 1 块，取回后校验 `len(records) == total`。
（这是**传输**分页，不是 DRC 分页——DRC 本身一次就给全量。）

### 4.3 qq.py 手工交叉验证（要求项）
手工 `qq.py _xcheck.js`（同样的 `eda.pcb_Drc.check(false,false,true)`，独立进程、独立解析）：

```
groups=[{name:"Connection Error", count:39, items:39,
         subs:["GND=2","VCC=2","GND_BK=2","XL2=2","$1N17527=2","RF=2","PT2=2","IP+5V=2",
               "$1N17186=2","$1N19139=2","$1N19304=2","PT1=3","SW_BK=2","$1N26963=2",
               "PWM_U=2","PWM_LU=2","PWM_V=2","PWM_LV=2","PWM_LW=2"]}]
items=39 declared=39
fingerprint={n_lines:1786, n_vias:196, n_pours:4, pours_filled:4, n_comps:166}
rule_config="自定义配置"
```

导出器同状态读数：`pass 0/1/2 = 39 条, declared=39 一致`，唯一 40 点/39 对
（多出的 1 个点：`(GND): U6_F23` 这一对焊盘被报了 2 个不同坐标）。
→ **手工调用与导出器逐组逐子类完全一致**，差异仅在导出器的“点级/对级”两种去重口径。

### 4.4 图元 id 可解析率（决定自动修复可行性）
* 当前板子状态（快照 C）：**40/40 = 100%** 的 DRC id 能在 `pcb_PrimitiveLine/Via/Pad.getAll()` 里查到；
* 抢救快照 A（导入前）在**现在的板子**上只有 `502/1400 = 35.9%` 可解析——
  因为重导 SES/重铺铜后 Track 的 16 位 id 全部重生成（594 条 Track-to-Track 全部失效）。
  → **修复向量必须在“同一板子状态”下同批导出**，否则会拿到失效 id（导出器已显式区分
  `unresolved` 动作并给出原因，不会静默按错图元算向量）。

### 4.5 单位校验
对 1361 条带间距的违规，把 `param.minDistance` 文本解析回 mil 与 `raw×10` 比对：
**不一致 0 条**（容差 0.06 mil，覆盖文本 0.1 mil 精度）。

### 4.6 稳定性/容错（都实际触发过）
* `Error: undefined`（HTTP 500 / 扩展断连）：单 pass 失败会重试 2 次，仍失败则跳过该 pass，
  只要还有成功 pass 就继续导出并在报告里写 `pass_errors` 警告（实战触发：pass 0/1 全挂、pass 2 成功）；
* 板子/规则在采样期间被改动：`per-pass` 原始计数不一致会自动告警，唯一数取并集；
* 桥接未监听 / `check` 不存在：直接 `DRC API 不可用: <原因>` 退出码 2，**不会静默返回空**。

### 4.7 已知局限
* 坐标 `pos` 是违规位置（碰撞点），不是图元中心；个别项为 0/极小值（重叠），已在 §5 分类剔除；
* 连接类违规没有 `minDistance/shouldBe`，只能给配对与坐标；
* `--recover` 抢救的历史快照没有当时的板子指纹（元数据里明确标注 `recovered`）。

## 5. 剩余问题与“按类别修复”建议

### 5.1 剩余 39 个连接错误（当前唯一未清项）
`Connection Error / SMD Pad 37 + TH Pad 3`，19 个网络，两两成对（同网两颗焊盘彼此不连通）：

| 网络 | 焊盘对（示例） | 网络 | 焊盘对（示例） |
|---|---|---|---|
| GND | `C55_1` ↔ `U6_F23`(另有一处) | PT1 | `R32_2` ↔ `U1_6` + `LED1_1`(TH) |
| PT2 | `R31_1` ↔ `LED1_3`(TH) | VCC | `R33_1` ↔ `U2_8` |
| GND_BK | `C30_2` ↔ `U4_4` | SW_BK | `R9_1` ↔ `U4_5` |
| IP+5V | `Q1_3` ↔ `U8_4` | XL2 | `U6_F2` ↔ `X2_2` |
| RF | `C55_2` ↔ `U6_H23` | $1N26963 | `R33_2` ↔ `U7_1`(TH) |
| PWM_U/LU/V/LV/W/LW | `U1_25..37` ↔ `U4_27..32` | $1N17186 | `C45_1` ↔ `U6_C1` |
| $1N17527 | `U6_B5` ↔ `U6_E24` | $1N19139 | `C62_2` ↔ `U6_AC5` |
| $1N19304 | `L4_2` ↔ `U6_AB2` | | |

处理顺序建议：
1. **先确认铺铜填充**（`getCopperRegion() != undefined`）：本次实测 0 铺铜时连接错误 45，
   4 铺铜填充后 39 —— 铺铜状态直接影响这类计数；
2. **GND / GND_BK / VCC / IP+5V 这类电源网**：多数是“只有铺铜连接、没有缝合孔/热焊盘”。
   在当前 39 条里它们与信号网成对出现（如 `GND: C55_1 ↔ U6_F23`），建议对这 19 对逐个
   从 `drc_commands_after_reimport.json` 取坐标，做“最近同网图元 → 补短线/加过孔”的小步骤修复；
3. **PWM_*/SW_BK/RF/PT1/PT2/$1Nxxxxx 信号网**：属于**没布通的短段**，补一条同层短线（或换层+过孔）
   即可，不用动铺铜；
4. 每修一批后用 `python drc_full.py --diff drc_full_after_reimport.json` 复核“消失/新增/仍在”，
   确保只减不增。

### 5.2 间隙违规（已清零，但要有回归检测）
* 导入前 1361 条里有 **531 条间距 = 0.00 mil（重叠/交叉）**：这类**不能靠微调修**，
  必须重布（`drc_to_commands.py` 会标成 `manual_reroute`）；
* 另有 830 条是“差一点点”（<0.5 mil 者 113 条、0.5–1 mil 者一批），这类才是
  `shift_track` 微调的目标：`drc_to_commands.py` 会给出“沿法线推 deficit+margin mil”的向量，
  并用平移后重算的最近距离给出 `expected_new_gap_mil` 供修复器验证；
* 回归检测：任何改动后用 `--diff` 对比旧快照；**间隙违规重新出现时优先检查是否又注入了
  `copilot_router_*` 规则**（`rule_config.copilot_router_residue` 字段会自动带出来）。

## 6. drc_to_commands.py（修复动作清单）

```bash
python drc_to_commands.py --json drc_full_after_reimport.json --out cmds.json --tsv cmds.tsv
python drc_to_commands.py --selftest        # 几何/向量自检（不碰板子）
```

* 动作分类：`shift_track`（可微调，带向量）、`manual_reroute`（间距≈0，需重布）、
  `manual_connect`（孤岛网络）、`manual_move_fixed`（两端都是 Via/Pad/Hole，需人工决定）、
  `unresolved`（id 在当前板子上找不到 → 快照失效）；
* 每条动作含：`target{id,suffix,net}`、`other{...}`、`vector_mil/mm`、`deficit_mil`、
  `margin_mil`、`expected_new_gap_mil`、`layer`、`at_mm`、`pair_sig`、`reason`；
* 几何来自 `pcb_PrimitiveLine/Via/Pad.getAll()`（mil），分块拉取；Track-Track 用
  “最近点 + 法线 + 两个方向试算取更优”，Track-障碍用“背离障碍中心方向”，
  障碍半径按 pad 描述近似（RECT 取外接半径），结果都以“平移后重算最近距离”自校验；
* 自检 11/11 通过（平行线取法线方向、平移量=deficit+margin、交叉线判 0、
  障碍方向、间距 0 → manual_reroute、连接错误 → manual_connect、单位换算）；
* 当前 after 快照的输出：`manual_connect=40`，几何解析 **40/40 = 100%**，
  已生成 `drc_commands_after_reimport.json` / `.tsv` 供修复器直接消费；
* 对导入前快照的输出：`unresolved=898 / manual_move_fixed=325 / manual_reroute=138 /
  manual_connect=39`，几何解析 502/1400 = 35.9%（正好演示了“快照必须与板子同状态”）。

## 7. 文件清单

| 文件 | 内容 |
|---|---|
| `drc_full.py` | 全量导出器（`--json/--limit/--passes/--strict/--diff/--recover/--chunk/--bridge/--timeout`） |
| `drc_to_commands.py` | 违规 → 动作清单（`--json/--out/--tsv/--top/--margin/--move/--min-deficit/--selftest`） |
| `drc_full_before_reimport_recovered.json/.txt` | 快照 A：导入前 1400 条全量明细（从页内缓存抢救） |
| `drc_full_after_reimport.json/.txt` | 快照 C：导入后 40 点/39 对（含 before/after diff） |
| `drc_commands_after_reimport.json/.tsv/.txt` | 当前 39 个连接错误的动作清单（100% 解析） |
| `drc_commands_before_reimport.json/.txt` | 导入前 1400 条的动作分类（含 138 条 manual_reroute、deficit 排序） |
| `_probe_drc1..10.js`, `_xcheck.js` | API 探测/取证/交叉验证脚本（可复现每一步结论） |

## 8. 复现命令

```bash
cd D:/360Downloads/tourbox/pcb-layout
export PYTHONIOENCODING=utf-8
PY=C:/Users/yinsh/AppData/Local/Programs/Python/Python310/python.exe

# 全量导出（3 pass 并集去重）+ 明细 40 条/子类
$PY drc_full.py --limit 40 --json drc_full_after_reimport.json

# 与旧快照对比（消失/新增/仍在）
$PY drc_full.py --diff drc_full_before_reimport_recovered.json --json drc_full_after_reimport.json

# 板子已被改动、需要抢救历史结果时
$PY drc_full.py --recover --json drc_recovered.json

# 生成修复动作
$PY drc_to_commands.py --json drc_full_after_reimport.json --out cmds.json --tsv cmds.tsv
$PY drc_to_commands.py --selftest

# 手工交叉验证（要求项）
$PY qq.py _xcheck.js 600
```
