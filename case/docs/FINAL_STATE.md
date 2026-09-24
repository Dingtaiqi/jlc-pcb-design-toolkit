# tourbox eltie — PCB 现状与待办（最终交接）

## 板级现状（checkpoint `zwphef0gf8xaou2a`，已验证）
| 项目 | 数值 |
|---|---|
| 走线 | 1657 |
| 过孔 | 481 |
| GND 铜皮 | 2 个（TOP/BOTTOM 各一，**均已实填**） |
| DRC 间隙错误 | **0**（无任何短路） |
| DRC 连接错误 | 46 = GND 32 个焊盘 + 7 个网络 × 2 |
| ANT_KEEPOUT | 完好（region `b045853bc1d8bca7`，MULTI，x 84.6..90.5 / y 31.0..39.0）|

## 仍未布通的 7 个网络
`PWM_LU` `PWM_LV` `XL1` `ADC1.1` `SDO` `$1N19139` `PGND`

### 根因（已用障碍图证实，不是算法问题）
**U4（DRV8316）PWM 焊盘出口被"封死成死胡同"。**
以 `PWM_LU` 的焊盘 U4.28 (9.410, 44.691) 为中心做同规则洪泛：
- 可达自由格只有 **647 格**，bbox 仅 x 1.0..2.5 / y 52.1..55.1 的那一小片 —— 即一个竖直窄缝口袋，向上到 y≈47 就断。
- 封住该口袋的 4×3 mm 区域内：**走线 2397 格**（AVDD 560 / PWM_V 485 / PWM_U 468 / AGND 453 / PWM_W 296）、**焊盘 807 格**（C23/C24 的 AVDD 549 + GND 110）。

即：U4 上方既有扇出线 + C23/C24 焊盘把 6 路 PWM 的逃逸通道占满了。0.5 mm 间距 QFN 焊盘之间物理上不可能过线（需 0.431 mm，实际间距 0.25 mm），所以每路 PWM 只能从自己焊盘正上方出去——而那条竖直缝被邻路 PWM 的扇出线和 AVDD/AGND 占了。

### 已排除的伪原因
- 线宽不是原因：把目标网络窄化到 0.127 mm（板子最小），路径与拆线清单完全不变。
- 加权 A*（h×3、h×5）不能解决：只是把已通的走得更差（SDO 105→151 mm）。
- 只拆低价值网络也不行：PWM_LU/LV 必须穿越的集合里全是关键网络（VCC、XIN/XOUT、SWDIO、DRV_OFF、NSLEEP、AVDD、1V1、U/V/W、PWM_*），拆了就是安全缺陷。
- 拆线后无法局部缝合：拆线只放出被拆图元自身的宽度（≈0.63 mm），减去新线的净空带（0.504 mm）后两侧只剩 0.065 mm，被拆网络无路可绕。

## 建议的修复路径（按性价比排序）
1. **重做 U4 扇出（推荐）**：把 x 6.5..12.5 / y 44..48.5 这 4×3 mm 区域内的 AVDD / AGND / PWM_U / PWM_V / PWM_W / PWM_LW 走线整体铲掉，把 6 路 PWM + 4 路 SPI（SDI/SCLK/SDO/SCS0.1）当**一个束**统一重布，再把 AVDD/AGND 用更宽的线补回。该区域清空后自由格约 78%，容得下 10 根线（约需 3.5 mm 通道宽，双层可用约 12 mm）。
2. **挪 C23/C24（AVDD 去耦）1.5–2 mm**：它们的焊盘占了通道上方 549+110 格。挪件会打断自身连线，需要用路由器补回（本会话已有工具）。
3. **改布局**：用户已授权可移动 U1/U6。把 U1 向 U4 靠近可根本性缩短 U1↔U4 的 6 路 PWM + 4 路 SPI，但会牵动 U1 全部 ~60 脚，属于整板重布。

## 本会话发现并修掉的关键坑（避免重复踩）
1. **DRC 直接抛 `Error: undefined`（HTTP 500）**：根因是板上有 **22 个重复且未填充的 GND 铜皮**（每次 `plane()+runCopper()` 都会新建一对），原生 DRC 组合爆炸。删掉全部→只建 2 个并实填后 DRC 正常。
2. **`eda.pcb_Drc.check` 走桥接会在 32 s 被杀**：改 `bridge-server.mjs` 的 `REQUEST_TIMEOUT_MS` 30000→900000；桥重启后官方扩展约 90 s 自动重连。
3. **路由器注入的 DRC 规则**：`applyDrcRules()` 会给 31 个网络写入 `copilot_router_net_0_spacing`（0.59843 mm），造成 586 条"假违规"。用 `overwriteNetRules()` 把这些引用改回 `default` 后，才是板子真实工艺规则（线-线 0.102 / 线-焊盘 0.152）。
4. **`getState_Rotation()` 单位是弧度**（取值 0/±1.5708/3.1416），而 `Pad` 字符串是 `RECT,宽,高,圆角半径`（**第 4 个字段不是旋转角**）。把它当度用会让 0.4 mm 间距的 QFN 焊盘互相重叠成"墙"，把一切路由堵死。
5. **A\* 目标必须限制到达层**：否则会"到达"焊盘正下方另一层的格点，制造假连通。
6. **scipy `label(structure=ST8)` 允许对角夹缝穿越**，用于可达性判断会过于乐观（那是真实短路）；评估路由可行性要用禁止切角的规则。
7. **铺铜参数不要放松**：间隙 0.3→0.254 mm 会让 GND 孤立铜岛从 32 涨到 **220** 个连接错误，必须保持 `clearanceMm: 0.3, removeIslandsBelowMm2: 10`。

## 工具与产物
- `D:\360Downloads\tourbox\pcb-layout\r2\`：`build3.py`（按网络感知的障碍图 + 所有权标签）、`route5.py`/`route6.py`（A\\*，含加权与拆线）、`reach.py`/`diag_reach.py`/`map_u428.py`（可达性/障碍图诊断）、`emit3.py`（把 paths.json 落成真实走线+过孔）、`grid2.npz`
- `python`：必须用 `C:\Users\yinsh\AppData\Local\Programs\Python\Python310\python.exe`（有 numpy/scipy/shapely）
- 桥接：`node scripts/bridge-server.mjs`（端口 49620，`node C:/Users/yinsh/.dsh/skills/easyeda-api/scripts/bridge-server.mjs`）
- 关键检查点：`zwphef0gf8xaou2a`（当前干净态）、`tj44xka0hz4ak0ea`、`5hpgoean4ja5fc1f`

## 用户仍需手工完成
天线匹配（L7 RFECA3216060A1T）——按用户要求由其本人处理，ANT_KEEPOUT 已就位。
