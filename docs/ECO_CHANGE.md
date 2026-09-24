# 变更与换料流程（ECO-lite）

> 适用场景：原理图被改动（改值 / 换料 / 增删网络与器件）之后，怎么**安全地**同步到 PCB、
> 怎么**验证没把已布好的铜弄坏**、怎么**换料而不改板**、交付文件要跟着改哪些。
>
> 这一章是从真实事故里长出来的：一次"只改了值"的改动，DRC 报出 3 条 `Netlist Error / Import Changes`，
> 如果不加验证直接导入，已布的铜可能被按新网表删掉。

## 何时用

| 触发信号 | 含义 |
|---|---|
| DRC 出现 `Netlist Error`，`ruleName = Import Changes`，**无坐标**、`id=err0/err1/…` | PCB 与原理图**不同步**（不是制造缺陷，但绝不是 0 违规） |
| 原理图里改了 Value / 型号 / 供应商料号 | 大概率同步后只影响元件属性，**不碰铜** |
| 原理图里改了连线、增删器件 | 同步后**会**改铜：可能删网络、删铜、需要补布线 |

**报数口径**：出现这类条目时，只能说「**0 条布线/间距违规 + N 条同步提示**」，
不能笼统说「DRC 0 违规」——这是交付声明的可信度问题。

## 第 0 步：先判定性质（三选一，决定后面多小心）

| 性质 | 判据 | 风险 |
|---|---|---|
| 只改值/属性 | 网络名与每网引脚数**完全不变** | 低：只需重出 BOM/坐标 |
| 换料（同封装） | 器件封装/焊盘不变，仅料号与规格变 | 低：**Gerber 不动** |
| 换料（换封装）/ 增删器件 / 改网络 | 引脚↔网络映射变化，或封装变化 | **高**：必须重布线、重铺铜、重跑 DRC、重出 Gerber |

判定手段：`tools/netlist_fetch.py`（取两侧网表） + `tools/netlist_props_diff.py`（属性 diff） +
`tools/net_inventory.py`（每网铜量）。**不要凭"我记得没动网络"**——要拿数据。

## 第 1 步：同步前存档（三件套，缺一不可）

```bash
python pcbai.py run tools/ping.js        # 先确认通道活着、EDA 主线程不忙
# 1) 图元级 checkpoint（可视化回滚）
#    走 MCP: save_checkpoint_for_current_page
# 2) 网络/铜量基线（数字级回滚依据）
python tools/net_inventory.py             # -> _pcb_net_inventory.json
cp _pcb_net_inventory.json snapshots/inventory_before.json
# 3) 网表基线（元件属性）
python tools/netlist_fetch.py pcb         # -> _netlist_pcb.raw.json
cp _netlist_pcb.raw.json snapshots/netlist_before.raw.json
# 4) 交付文件基线
cp deliver/Export_BOM.xlsx snapshots/Export_BOM_before.xlsx
```

## 第 2 步：导入变更

**走 MCP 的专用接口**（`import_pcb_changes`），不要用原生 API 手搓。
注意：EasyEDA 会弹出「导入变更」对话框，**最后一下确认必须由人点**（工具只能触发）。

导入前对着弹窗清单快速核对：预期只有"值/属性"类条目；若出现**网络增删**，停下来先看第 0 步的判定。

## 第 3 步：导入后三项硬验证（这一节是本章核心）

```bash
python tools/netlist_fetch.py pcb && cp _netlist_pcb.raw.json _netlist_pcb_after.raw.json
python tools/net_inventory.py
python tools/net_inventory_diff.py snapshots/inventory_before.json _pcb_net_inventory.json
python pcbai.py drc
```

必须同时满足：

1. **铜量 diff 全空**：无网络消失 / 无新增 / 每网线数·过孔数·焊盘数不变 → 证明没删铜
2. **DRC 复跑 0 违规** → 证明同步提示消失、且没引入新违规
3. 交付文件已按新属性重出（BOM、坐标）

任一条不满足 → 用 checkpoint 回滚，别硬着头皮往下走。

## 第 4 步：换料验证链（六道关）

1. **先立约束，再找料**：从器件手册抄下硬指标。例：该低功耗 MCU 的 LFXO 要求
   `CL ≤ 7pF（typ 7pF）`、`ESR ≤ 70kΩ`。——没有约束的选料是瞎猜。
2. **找候选**：EasyEDA 器件搜索（`component_search`，吃 **MPN 或 part_uuid**，**不吃自由文本**）
   或立创商品页搜索。同族型号往往一次给出 5 个规格变体，直接横向比。
3. **核验规格，不要靠型号猜** ★：去立创商品页，页面里有结构化数据可直接机器核验——
   `tools/lcsc_verify.py` 会打印 `Load Capacitance / ESR / Frequency / Tolerance / 温度 / 封装码 / 价格 / 库存`。
   **反面教训**：我按"R 版就是 7pF"去推断，实测该料是 **12.5pF** ✗——差点把超规格的料当成合格料。
4. **封装一致性（决定 Gerber 要不要重出）**：
   - 封装名/封装码相同（本例双方都是 `SMD3215-2P` / `osc-smd_l3.2-w1.5`）→ **Gerber 不动** ✓
   - 封装变了 → 回到布线与 DRC 全流程，别想省事
5. **价格与库存**：立创国内页给人民币与现货数（本例 `¥0.8601`、现货 `1225 pcs`）；
   国际页给美元。**采购前确认现货**，否则交付会卡在备料。
6. **交付文件更新**（见下节），并给工厂一张**换料说明**。

## 交付文件更新清单

| 文件 | 何时需要更新 |
|---|---|
| `Export_BOM.xlsx` | 每次属性变化后重出（官方导出） |
| `Pick_Place`（贴片坐标） | Value/Comment 变化后重出（坐标本身不变，但要重出以同步字段） |
| `BOM_修正版.csv` | 官方导出缺料号/需立即下单时用；`utf-8-sig` 编码，Excel 直接打开不乱码 |
| `单板装配清单.csv` | 值/料号变化 |
| `核对BOM_对账.csv` | 与工厂 BOM 的对账；换料时把状态标成"已换料 待工厂同步" |
| `变更说明_*.txt` | **每次换料都要有**：旧料 → 新料、为什么、封装是否变、数量、对贴片/采购的影响 |
| Gerber / 坐标几何 | **同封装换料时不需要重出**（这条要明确写进交付说明，省一次投板确认） |

## 实战案例：X2 32.768kHz 晶振（12.5pF → 7pF）

- **背景**：X2 是 该低功耗 MCU 的 LFXO（接 `其 LFXO 引脚`）。原选型 `<原选型料号>` = **12.5pF**，
  超出 该低功耗 MCU 的 `CL ≤ 7pF` 规格 → 上电走时精度不达标（属于**真设计错误**，不是吹毛求疵）。
- **改法**：原理图里把 X2 的值标注为 `32.768kHz 7pf`。这一步本身没联网表 → 铜零风险。
- **代价**：编辑值的时候**LCSC 料号被清空**了 → 工厂拿不到料 → 必须补料号。
- **选料**：立创/Library 搜索同族，核验后选 **EPSON `<新选型MPN>` / `<新料号>`**
  （`7pF`、`ESR 50kΩ`（余量优于 70kΩ 上限）、`±20ppm`、封装 `SMD3215-2P` 与旧料**同封装** →
  **PCB/Gerber 无需改动**、现货 1225、¥0.8601）。
  备选：`<备选MPN>`（<备选料号>，7pF 但 ESR 压线 70kΩ，$0.614）。
- **同步动作**：checkpoint → 导入变更（人工确认）→ 铜量 diff（**零变化** ✓）→ DRC（**0 违规** ✓）
  → 重出 BOM/坐标 → 更新装配清单/对账表 → 写换料说明。
- **结果**：`单板装配清单.csv` 的 X2 行 = `32.768kHz 7pf / FC-135R_L3.2-W1.5 / <新料号>`；
  换料说明直接可发给贴片厂；Gerber 不动。

## 反面教训（都真实发生过）

- **靠型号猜规格**：把 "FC-135R" 默认成 7pF ✗ → 实测 12.5pF。**一定要抓页面结构化数据核验**。
- **用 `pcb_Net.getNetlist()` 做"值 diff"**：该接口**不携带元件实例值** → 导入前后网表字节完全相同，
  会得出"属性没变"的**假阴性** ✗。值要从 **BOM 导出**或**原理图侧**取。
- **`pcb_PrimitiveComponent.name` 不是值**：它是显示表达式 `={Value}` ✗，别拿它当 Value。
- **当前活动文档决定 API 有没有数据**：`eda.sch_*` 只在原理图页激活时才有效；
  拿错文档不报错，只返回**空数组**，很容易误判成"这个设计没有网络"。
- **重 API 会锁死主线程**：`getCurrentProjectAllNets()`、`sch_Netlist.getNetlist()` 在本设计上把 EDA
  拖到只能人工重启。**默认不碰**；必须用时单次调用 + 大超时 + 不并发重试。
