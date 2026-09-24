# EasyEDA Pro 自动化工具与 API 调用手册（交接给其他 AI）

项目：`tourbox eltie`（2 层板 90×90 mm）
PCB 文档 uuid：`a13a9a0e834c40d3a24ee99ae8ff4e1c`
原理图 uuid：`0bbbb03f76ff47e4aa2216733d672a84`（注：以 `get_current_project_info` 实际返回为准）
当前安全检查点：`jeju0vl6zovf6bih`（DRC 间隙错误 = 0）

---

## A. MCP 工具表（`mcp__easyeda__*`）

安装：MCP 服务 `easyeda-copilot-mcp` v1.1.9（MIT，github.com/biosshot/easyeda-copilot）
+ 路由包 `eda-copilot-router` v0.3.0（内部调用 KiCadRoutingTools 0.21.3 + EasyEDA WASM 规划器）。
挂载配置：`C:\Users\yinsh\.dsh\profiles\web\cordis.patch.yml`（serverName `easyeda`，stdio，node `C:/Program Files/nodejs/node.exe`，args `.../easyeda-copilot-mcp/dist/index.js`）。
EasyEDA 内需启用 `easyeda-copilot` 扩展。

### A1. 读取 / 检查类

| 工具 | 关键参数 | 作用 | 注意 |
|---|---|---|---|
| `get_current_project_info` | — | 当前项目树 + 文档元数据（BOARD 项含 schematic/PCB uuid） | 切换项目/文档前先调 |
| `get_current_pcb` | — | 读取当前 PCB：层、板框 polygon、166 个器件、pad/net、走线、铺铜 polygon | 板子大时返回 “Pcb too big, saved to file”，返回 `path` 指向 JSON |
| `get_current_page_schematic` | — | 当前原理图页的器件/引脚/网络 | 只在原理图页有效 |
| `get_all_projects` | — | 全部可访问的团队/文件夹/项目树 | — |
| `list_easyeda_instances` | — | 已连接的 EasyEDA 实例列表 | 多开时用 |
| `select_easyeda_instance` | `instanceId` | 指定本 MCP 使用哪个实例 | — |
| `inspect_component` | `designator`, `radius` | 单个器件的 PCB 信息 + 半径内邻居 | **当前标签页必须是 PCB**，否则 “Failed getPcb” |
| `inspect_net` | `net`, `drc_limit` | 指定网络的长度/线宽/过孔/层/连接焊盘/DRC 违规 | 同上 |
| `get_pcb_drc_rules` | — | 全局限值、net class、差分对、等长组、逐网络覆盖 | — |
| `get_pcb_stack_layers` | — | 铜层数与可布线信号层 | 写路由 DSL 前必看 |
| `get_pcb_component_sizes` | `designators[]`, `includeAll` | 解析元件焊盘外形尺寸（mm） | **大量 LCSC 库元件解析失败**（本板 166 个只成功 33 个） |
| `check_pcb_drc` | `limit` | 运行 EasyEDA DRC，按类别分组返回 | **大板会 Request timed out**；改用 B 节的桥接方式 |
| `list_checkpoints` | — | 已存检查点 | — |
| `preview_pcb` | `layers[]`, `highlight_net`, `highlight_component`, `highlight_net_colors`, `highlight_component_colors`, `zoom{mode:full/net/component/bbox}`, `padding_mm` | 渲染 PNG | 返回 `image_path`；`zoom.mode=bbox` 需 `{x,y,width,height,unit:"mm"|"rel"}` |

### A2. 写入 / 修改类（PCB）

| 工具 | 关键参数 | 作用 | 注意 |
|---|---|---|---|
| `make_pcb_layout` | `file`（PCB 布局 DSL）、`wait_ms` | 生成器件摆放（**不装配、不布线**） | 本板因 “Missing real footprint for SW1/L1” 失败，最终改用官方 API 摆放 |
| `assemble_pcb_layout_on_current_pcbdoc` | `layoutId` | 把 `make_pcb_layout` 的结果装配到当前 PCB | 需先 `open_document` 打开目标 PCB |
| `run_pcb_router_dsl` | `file`（路由 DSL）、`wait_ms` | 执行铜皮/DRC/布线 DSL（动词见 C 节） | 返回 `operation_id`；`status:complete` 后看 `copper.pours_rebuilt` |
| `apply_operation` | `operation_id` | 重试套用已算好的结果 | — |
| `cancel_operation` | `operation_id` | 取消 | — |
| `wait_operation` | `operation_id`, `wait_ms` | 等待长任务 | — |
| `import_pcb_changes` | `schematic_uuid?` | 把原理图改动导入当前 PCB | — |
| `save_doc` | — | 保存当前文档 | — |
| `sync_current_document` | `settle_ms` | 保存 → 关标签 → 重开（强制同步） | 文档子系统卡死时用 |
| `modify_name` | `doc{uuid\|board_name}`, `name` | 改名 | 用 UPPERCASE 或 PascalCase |
| `save_checkpoint_for_current_page` | — | 存检查点，返回 `checkpointId` | **改动前必存** |
| `restore_checkpoint_for_current_page` | `id` | 回滚 | 回滚后 `pcb_*` 可能全部 HTTP 500，用 `open_document` 重绑；且铜皮会变**未填充**，必须重铺，否则 DRC 出现几百个假的 GND 连接错误 |
| `open_document` | `document_uuid`, `project_uuid` | 打开文档/项目（切换前自动保存，保存失败则中止切换） | 也是 DRC 卡死后的解药 |

### A3. 原理图 / 其它

| 工具 | 关键参数 | 作用 |
|---|---|---|
| `extract_circuit_on_current_page` | `add_components[]`, `add_reused_blocks[]`, `rm_components`, `external_rm_connect`, `external_connect` | 在当前原理图页增删器件、连信号（每个新增件必须给 `part_uuid`）|
| `beautify_schematic_on_current_page` | `blocks{}`, `draw_block_box` | 按功能块重排整页（会先存检查点，失败自动恢复）|
| `annotate_designators` | `mode: preserve\|resequence` | 位号标注（保留前缀，只拍尾号）|
| `search_reused_block` | `query`, `page`, `limit` | 搜索可复用电路块 |
| `component_search` | `part_uuid` 或 `MPN` | 搜元件（精确 MPN 优先）|
| `create_doc` | `doc{...}` | 建工程/原理图/页/PCB/板（project 用实验性 beta API，**不会自动打开**）|
| `delete_doc` | `doc{uuid\|board_name}` | 删除文档（破坏性）|

---

## B. 官方 `eda.*` API（经本地桥接调用，功能远多于 MCP）

安装：技能包 `C:\Users\yinsh\.dsh\skills\easyeda-api\`（v1.1.36），EasyEDA 内启用 `run-api-gateway` 扩展。

### B1. 启动与调用

```bash
# 启动桥（端口 49620）
cd C:/Users/yinsh/.dsh/skills/easyeda-api && node scripts/bridge-server.mjs
# 健康检查
curl -s http://localhost:49620/health
# 执行任意 JS（在 EasyEDA 页面上下文，支持顶层 await，必须 return 可 JSON 序列化值）
curl -s -X POST http://localhost:49620/execute -H "Content-Type: application/json" \
     -d '{"code":"const L=await eda.pcb_PrimitiveLine.getAll(); return L.length;"}'
# 返回 {"success":true,"result":...,"windowId":"..."}
```

**已打的补丁**：`bridge-server.mjs` 里 `REQUEST_TIMEOUT_MS` 30000 → 900000（否则 DRC 在 32 s 被杀）。桥重启后官方扩展约 90 s 自动重连。

### B2. 常用对象与方法（实测可用）

| 对象 | 方法 | 说明 |
|---|---|---|
| `eda.pcb_PrimitiveComponent` | `getAll()`（**要 await**）| 器件数组 |
| 〃 | `getState_Designator/X/Y/Rotation/Layer/Footprint/PrimitiveId()` | 坐标单位 **mil** |
| 〃 | `await c.getAllPins()` / `setState_*()` + `await c.done()` | 读引脚 / 改属性 |
| `eda.pcb_PrimitiveLine` | `getAll()`、`get(id)`、`create(net, layer, x1, y1, x2, y2, width, lock)`、`delete(ids[])` | 走线；坐标与线宽均 **mil** |
| 〃 | `getState_Net/Layer/StartX/StartY/EndX/EndY/LineWidth/PrimitiveId()` | — |
| `eda.pcb_PrimitiveVia` | `getAll()`、`create(net, x, y, holeDiameter, diameter)`、`delete(ids[])` | **钻孔在前、外径在后** |
| `eda.pcb_PrimitivePad` | `getAll()` | 焊盘 |
| 〃 | `getState_Net/Layer/X/Y/Pad/PadNumber/Hole/Metallization/HoleOffsetX/Y()` | `Pad` 字符串格式：`RECT,宽,高,圆角半径`（**第 4 个字段是圆角，不是旋转角**）；`getState_Rotation()` 单位是**弧度** |
| `eda.pcb_PrimitivePour` | `getAll()`、`create`、`delete(ids[])`、`getCopperRegion()` | 铺铜；`getCopperRegion()` 返回 undefined = **未填充**（一定要填充，否则 DRC 崩）|
| `eda.pcb_PrimitivePoured` / `PrimitiveFill` | `getAll()`、`create(...)` | 已填充铜 / 填充区 |
| `eda.pcb_PrimitiveRegion` | `getAll()`、`create(layer, complexPolygon, ruleType, regionName, lineWidth, lock)`、`delete(ids[])` | 禁布/规则区；**最后几个 flag 必须传数字 0（传 false 会静默返回 undefined）**；`R` 模式下 Y 是**上边（max Y）**，矩形向下生长 |
| `eda.pcb_MathPolygon` | `createPolygon([...])`、`createComplexPolygon([...])` | 多边形构造 |
| `eda.pcb_Net` | `getAllNetName()`、`getAllPrimitivesByNet(net)` | 返回 `parentId, center.x/y, topWidth/topHeight, rotation, layerId, num` |
| `eda.pcb_Drc` | `check(strict, userInterface, includeVerboseError)` | 返回分组数组；`includeVerboseError=true` 时每条含 `objs[]`（**16 位十六进制真实图元 id**）、`obj1.suffix/obj2.suffix`（显示用短 id，**不能用于删除**）、`explanation.param`、`errData` |
| 〃 | `getNetRules()` / `overwriteNetRules(netRules)` | 逐网络规则（路由器会注入 `copilot_router_*`）|
| 〃 | `overwriteNetRules`、`getNetByNetRules`/`overwriteNetByNetRules`、`getRegionRules`/`overwriteRegionRules`、`getAllNetClasses`、`createDifferentialPair`/`deleteDifferentialPair`/`getAllDifferentialPairs`、`getCurrentRuleConfiguration`/`overwriteCurrentRuleConfiguration`、`getAllRuleConfigurations` | 规则管理 |
| `eda.pcb_Document` | `save()`、`clearRouting()`、`importAutoRouteSesFile(file)`、`importChanges`、`getPrimitivesInRegion`、`getPrimitiveAtPoint`、`zoomToBoardOutline`、`convertCanvasOriginToDataOrigin`… | **没有** `autoRouting()`；保存用 `save()`（不是 `dmt_Project.saveCurrentProject`）|
| `eda.pcb_ManufactureData` | `getDsnFile(fileName?)` | 导出 Specctra DSN（可交给 Freerouting 等）|
| `eda.dmt_Project` | `getCurrentProjectInfo()` | 项目信息 |
| `eda.sch_Drc` | `check(...)` | 原理图 DRC |

**发现 API 面的方法**（对任何对象都适用）：
```js
Object.getOwnPropertyNames(Object.getPrototypeOf(eda.pcb_Drc))
```

### B3. 两个必须知道的坑

1. **DRC 报 `Error: undefined`（HTTP 500）**：根因是板上有**多个互相重叠且未填充的铺铜**（每跑一次 `plane()+runCopper()` 就新增一对）。修法：删掉全部铺铜 → 只建 2 个（TOP/BOTTOM）并确认 `getCopperRegion()` 有返回。
2. **检查点回滚后**：`pcb_*` 全 500 → `open_document` 重绑；且铺铜变未填充 → 必须重铺，否则 GND 连接错误会从 32 涨到 353。

---

## C. 路由 / 铜皮 DSL（`run_pcb_router_dsl` 的输入）

权威声明文件：`C:\Users\yinsh\.dsh\mcp\easyeda-copilot\node_modules\eda-copilot-router\docs\routing-dsl.d.ts`
流程文档：`...\easyeda-copilot-mcp\docs\SKILL.md`

可用动词：`stack`、`drc`、`netClass`、`powerNet`、`signalNet`、`diffPair`、`matchedGroup`、`plane`、`polygon`、`viaStitch`、`onlyNets`、`ignoreNets`、`clearRouting`、`deleteDiffPair`、`deleteMatchedGroup`、`busDetect`
终止符：`applyDrcRules()`、`applyStackup()`、`runCopper()`、`runRouting()`、`runAll()`

**本板验证过的重铺脚本**（`D:\360Downloads\tourbox\pcb-layout\repour2.js`）：
```js
stack({ boardThicknessMm: 1.0, fallbackCopperThicknessOz: 1, layers: [
  { kind:"copper", name:"TOP", thicknessOz:1 },
  { kind:"dielectric", name:"core", thicknessMm:1.0, relativePermittivity:4.4, lossTangent:0.02, material:"FR-4" },
  { kind:"copper", name:"BOTTOM", thicknessOz:1 } ] });
plane({ net:"GND", layers:"OUTER", region: board(),
        zone:{ clearanceMm:0.3, removeIslandsBelowMm2:10 } });   // ← 不要放松这两个值
runCopper();
```
注意：**不要用 `stitching:{gridMm:4}`**（盲网格缝合孔会撞通孔焊盘，产生 hole-to-hole 错）；**铺铜间隙不要从 0.3 改到 0.254**（孤立铜岛会让 GND 连接错误从 32 涨到 220）。

已验证的差分对几何（USB 90 Ω）：`width 0.127 mm / gap 0.152 mm / TOP / ref GND` → 86.76 Ω（`verified:true`）。

---

## D. 自建网格路由管线（Python，本会话产物）

目录：`D:\360Downloads\tourbox\pcb-layout\`（必须用 `C:\Users\yinsh\AppData\Local\Programs\Python\Python310\python.exe`，其中已装 numpy/scipy/shapely；KRT 也依赖它，否则会去下载托管运行时并永久挂死）

| 文件 | 作用 |
|---|---|
| `extract_live.py` → `live.json` | 抓实时几何：`lines[pid,net,layer,x1,y1,x2,y2,w]`、`vias[pid,net,x,y,dia,hole]`、`pads[net,layer,x,y,padstr,hole,padnum,rot]`、禁布区/挖槽 |
| `build3.py` → `grid2.npz` + `grid2_meta.json` | 0.05 mm 栅格；按网络归属标签 `tr1/tr2`（走线+过孔）、`pad1/pad2`（焊盘）、`hard`（板外/挖槽/禁布）；对称净空：走线 0.102、焊盘/过孔 0.152、板边 0.3 |
| `route5.py` / `route6.py` | 严格 A\*（按网络感知：自家铜可穿行、别人家必须避让；过孔按 0.61 mm 另行判定；目标层限定）+ 加权回退 + 拆线 |
| `finalfix*.py` / `try*.py` / `try3.py`（通道指派）/ `try7.py`（**端点补线**修复） | 各种配置试验器 |
| `emit3.py` / `emit_c7.py` | 把 `{net:{w,pts}}` 落成真实走线与过孔（mil 换算、逐条重试）|
| `dump_drc.py` / `drc_list.py` | 跑 DRC 并在**页内**汇总（避免大响应 500）|
| `delvias2.py` / `delpours.js` | 按真实 16 位 id 删过孔 / 删全部铺铜 |
| `reach.py` / `diag_reach.py` / `map_u428.py` | 可达性判定、洪泛诊断、障碍图可视化（★注意 `np.nonzero` 返回 (行,列)）|
| `FINAL_STATE.md` / `HANDOVER.md` | 现状与交接记录 |

**修复策略（最有效）**：拆掉挡路线段后，**不要整网重布**，而是在该线段**原来的两个端点之间补一条短线**（严格 A\*，多轮迭代，先补靠焊盘/已有铜的），实测 14/14、47/52 成功。

---

## E. 其它 CLI 工具

| 工具 | 位置 / 用法 |
|---|---|
| Freerouting 2.4.1 | `...\Temp\eda\tools\freerouting-2.4.1.jar` + Temurin JDK 25（class 69）；`-de <dsn> -do <ses> -mp <passes> -mt <threads> -us greedy\|global\|hybrid -hr m:n -is sequential\|random\|prioritized -dr <rules> -l en\|zh`；线程默认 = 逻辑核数−1 |
| Specctra 往返 | `eda.pcb_ManufactureData.getDsnFile()` → Freerouting → `eda.pcb_Document.importAutoRouteSesFile(file)` |
| DSN 导出 bug（EasyEDA 侧）| 声明层名为 `TopLayer/BottomLayer`，但所有走线写成 `(path 1 …)/(path 2 …)`；需把 `(path 1 ` → `(path TopLayer `、`(path 2 ` → `(path BottomLayer ` 后再交给 Freerouting，否则已有铜会被丢弃 |
| KRT 常量补丁 | `...\eda-copilot-router\package-dist\chunk-FQB5YI4I.js`：`KRT_MAX_POST_MAIN_REPAIRS 8→24`、`KRT_MIN_POST_MAIN_REPAIR_BUDGET_MS 15e3→18e4`、`KRT_MAX_POST_MAIN_REPAIR_BUDGET_MS 6e4→6e5`、`KICAD_NET_RESCUE/KICAD_TERMINAL_ESCALATION/KICAD_DYNAMIC_ITERATIONS = "1"`（改完需重启 MCP 才生效）|

---

## F. 单位 / 约定速查

| 项 | 约定 |
|---|---|
| 官方 `eda.*` 坐标 | **mil**（1 mil = 0.0254 mm）|
| 层号 | `1 = TOP`，`2 = BOTTOM`，`12 = MULTI` |
| 焊盘旋转 | `getState_Rotation()` = **弧度**（0 / ±1.5708 / 3.1416）|
| 焊盘形状串 | `RECT,宽,高,圆角半径`；`OVAL/ELLIPSE,宽,高`；`NGON,直径,边数`；`POLY,...` |
| 通孔判定 | `getState_Hole()` 非 `"null"` |
| 本板 DRC 真实规则 | 线宽 min 0.127 / pref 0.254 / max 2.54 mm；过孔 0.5/0.61/10 mm；钻孔 0.3/0.305/6.3；间隙 线-线 0.102、线-焊盘 0.152、线-过孔 0.152、线-铜 0.254、线-板边 0.3、线-孔 0.175 mm |
| 板框 / 坐标 | 90×90 mm，x 0..90，y −7.20..82.80 |
| 滚动轮挖槽 | MULTI 填充 `e602`：x 1.14–21.34 / y 50.80–75.44（L 形，**全高障碍**）|
| 天线禁布区 | region `b045853bc1d8bca7`，MULTI，x 84.6–90.5 / y 31.0–39.0（NO_POURS + NO_FILLS）|
| 三层地 | `GND`（124 焊盘，双面铺铜）、`PGND`（10）、`AGND`（9，U4 周围独立岛）；网络联结：R14 PGND→GND、R13 AGND→GND、R12 GND_BK→PGND |

---

## G. 工作流程检查清单（给下一个 AI）

1. 先 `get_current_project_info` → `open_document(PCB uuid)`（保证活动标签是 PCB）。
2. **改动前** `save_checkpoint_for_current_page`。
3. 启动/确认桥：`curl http://localhost:49620/health` 要 `edaConnected:true`；否则等 90 s 或重启桥后等扩展重连。
4. 用 B2 的 API 做事；长脚本拆小（单次 `/execute` 响应过大会 500）；DRC 在页内汇总后再 return。
5. DRC 验证后：`save_doc` + `save_checkpoint_for_current_page`。
6. 回滚后必做：`open_document` 重绑 → 删铺铜 → 重铺 → 再 DRC。
7. 天线匹配由用户手工完成（L7 RFECA3216060A1T）。
