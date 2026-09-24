# PCB-AI Toolkit
让 AI 能**可靠地**参与 PCB 设计与改板的工作流 + 工具集。

> 实战来源：一块 4 层 90×90mm 力反馈旋钮板（RP2350B + nRF52840 + DRV8316 + AS5600），
> 从「1400 条 DRC 错误、多处断网」做到「DRC 0/0 + 免费工艺档孔径 + 全文件齐备」。

## 三条核心思想
1. **不靠"看"，靠"量"** —— 所有几何判断都从 EDA 取真值（图元 API 的坐标/线宽/孔径/层），不靠截图或猜测。
2. **一次只动一类 + 每步自证** —— 任何加铜/挪件后必须 `重灌铜 → 重建连通图 → 全量 DRC`，判据是「违规数不增」；连接类判据是「该网连接错误数下降」。
3. **约束必须写全** —— 铜间距、**孔到孔（同网也查）**、**通孔焊盘钻孔**、层别、板厂工艺档，缺一条就会产生假判据。

## 架构
```
agent(AI) ──► CLI: pcbai.py ──┬─► Bridge  : 在运行中的 EasyEDA 里执行 eda.* JS (WS :49620)
                              ├─► Geom    : 旋转矩形 SDF / 孔到孔 / 分层障碍 / 局部预筛
                              ├─► Routers : A*(二叉堆) / 过孔择位 / BGA dogbone / fanout 重布
                              ├─► Verify  : DRC 全量导出(3pass 去重) / 连通性 / 预生产检查
                              └─► MFG I/O : 导出 / 叠层说明 / 立创比价 / 工厂 BOM 核对
```

## ★ 启动顺序(重要)
```
① 先起桥接   python tools/bridge-watchdog.py    (或双击 tools/start-bridge.cmd)
② 再启动 EasyEDA
③ 若 watchdog 提示"EDA 侧未连接": 到 EasyEDA 里打开 run-api-gateway 扩展, 点一次「重新连接」
```
原因: 该扩展**只在加载那一刻扫描端口, 不会自动重试** —— 所以顺序反了(先开 EDA 再起桥接)就必须手点一次。


## 真实案例（`case/`）

`case/` 是一块**真做出来的板子**：90×90mm 四层、双面贴片、172 元件、**DRC 0 违规**、最小钻 0.305mm（免加钱档）。

- **`case/PIPELINE.md`** ★ —— 布线全流程 9 阶段（约束 → 放置 → 自动布线 → 补线 → 铺铜 → DRC 归零 → 可制造性 → Mark 点 → 交付），每阶段写明判据与坑
- `case/docs/` —— 过程文档：交付总说明、补线流水账、DRC 全量报告、断点续跑
- `case/layout-scripts/` —— 33 个按阶段精选脚本（放置校验 / A\* / 扇出 / RF / DSN-SES 流水线 / 校验）
- `case/board_snapshot.json` —— **板子文本快照**：1926 线 / 268 过孔 / 656 焊盘（可 diff、可复算）
- `case/images/` —— 全板渲染图（顶/底）+ Mark 点实测图
- `case/deliver/` —— 交付件：Gerber zip、BOM、贴片坐标、装配清单、给贴片厂的工艺要求、换料说明

> ⚠️ 案例含具体产品设计数据；**公开仓库**请自行评估是否保留 `case/`（详见 `case/README.md`）。

## ★ 换料 / 变更怎么走（别硬闯）

原理图一被动过，PCB 与原理图就会失去同步（DRC 出现 `Netlist Error / Import Changes`，
无坐标、`id=err0/1/2`）。**在动手之前先读 `docs/ECO_CHANGE.md`**，核心就三步：

```bash
python pcbai.py ping                      # ① 通道/主线程探活
# ② 同步前存档: checkpoint + 铜量基线 + 网表基线 + BOM 基线
python pcbai.py inv       && cp _pcb_net_inventory.json snapshots/inventory_before.json
python pcbai.py netlist pcb && cp _netlist_pcb.raw.json snapshots/netlist_before.raw.json
# ③ 导入变更(MCP 弹窗人工确认) -> 导入后硬验证
python pcbai.py inv && python pcbai.py invdiff snapshots/inventory_before.json _pcb_net_inventory.json
python pcbai.py drc                       # 必须 0 违规(同步提示消失)
```

**换料选型**用核验器，不要靠型号猜：

```bash
python pcbai.py lcsc --file page.html --fp SMD3215-2P --need "Load Capacitance=7pF" --need "ESR<=70k"
# 国际页(lcsc.com)和国内页(item.szlcsc.com)两种格式都支持; 会打印规格/封装码/价格/库存, 并判断封装是否一致
```

### 两条铁律

1. **同封装换料 → Gerber 不用重出**（本例 X2：SMD3215-2P → SMD3215-2P，焊盘/坐标/丝印全不变）
2. **换封装、增删器件、改网络 → 必须重布线 + 重铺铜 + 重跑 DRC + 重出 Gerber**

交付文件更新清单、换料说明模板、以及一个真实的 32.768kHz 晶振 12.5pF→7pF 案例，
都在 `docs/ECO_CHANGE.md`。

## 快速开始
```bash
# 0) 启动桥接（独立 Node 进程，需在 EasyEDA 里启用对应扩展）
node "%USERPROFILE%\.dsh\skills\easyeda-api\scriptsridge-server.mjs"
# 1) 自检 / 基线
python tools/drc_full.py --limit 20
python tools/extract_live.py
# 2) 改板（脚本化几何操作）
python tools/qq.py my_route.js
# 3) 自证三连
python tools/qq.py tools/repour_once.js      # 重灌铜
#   （然后调 MCP sync_current_document 重建连通图）
python tools/drc_full.py --limit 0           # 全量 DRC（判据：违规数不增）
# 4) 交付
python tools/export_all.py
```

## 目录
- `tools/`  —— 可直接跑的工具（桥接、DRC、导出、快照、比价、BOM 核对、铺铜/网规修复）
- `docs/`   —— WORKFLOW.md（标准流程）、PITFALLS.md（**必读的坑单**）
- `examples/` —— 几何脚本样例（A* 布线段、过孔择位、dogbone、fanout 重布）

## 现状 / 路线
- v0.1（当前）：工具集 + 流程 + 坑单 + CLI 骨架，验证于真实板子
- v0.2：把几何引擎抽成独立 Python 包（脱离浏览器也能算），支持"整网重布 + 约束求解"
- v0.3：把 WORKFLOW 做成可被 agent 调用的技能（skill），并接入立创价格/库存做选型闭环
