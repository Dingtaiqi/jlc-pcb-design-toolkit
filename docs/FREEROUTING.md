# 开源 Java 自动布线器（Freerouting）集成手册

> 这是 `case/` 那块板子**真正跑过全局布线**的引擎。工具包不 vendor 它（GPL-3.0 三方二进制 +
> 62MB JAR + 291MB JDK，塞进 git 是灾难），而是把**集成方式、参数、坑、验证闭环**固化在这里。

## 1. 它是什么 / 从哪来

| 项 | 值 |
|---|---|
| 项目 | **Freerouting**（开源，Specctra `.dsn` / `.ses` 罗马规约的路由器） |
| 版本（本项目实测） | **freerouting-2.4.1.jar**（62MB） |
| 运行时 | **JDK 25**（Temurin，291MB 解压）；FR 2.4.1 的 class 版本是 69，JDK 17 跑不起来 |
| 本地路径 | `tools/freerouting-2.4.1.jar` + `tools/jdk-25.0.4.1+1/`（本仓库不收录，见 `tools/freerouting.py install`） |
| 官方发布 | GitHub Releases（下载 `freerouting-<ver>.jar`）；JDK 用 Temurin/Adoptium |

**许可证注意**：Freerouting 是 GPL-3.0。**不要在业务仓库里 vendor 它的 JAR**（除非你的项目也 GPL）。
用 `tools/freerouting.py install` 按需下载到本地即可。

## 2. 三段式流水线（EasyEDA Pro → FR → 回写）

```
① 导出 DSN   eda.pcb_ManufactureData.getDsnFile()          →  tools/dsn_export.py   （★必须打层名补丁）
② 跑布线     java -jar freerouting-2.4.1.jar -de … -do …    →  tools/freerouting.py run
③ 回写 SES   eda.pcb_Document.importAutoRouteSesFile(f)     →  tools/ses_import.py  （★回写后必须修 4 处）
```

### ① 导出 DSN：两个必须处理的坑

```bash
python tools/dsn_export.py --out work/board.dsn
```

- **★ 层名补丁（最关键）**：EasyEDA 在 DSN 头部声明层名是 `TopLayer/BottomLayer`，
  但**所有走线却写成 `(path 1 …)` / `(path 2 …)`**。Freerouting 按数字找不到层名 →
  **把已有铜全丢掉**（等于"未布线"从头开始）。导出器会自动补丁：

  ```
  (path 1  →  (path TopLayer
  (path 2  →  (path BottomLayer
  ```

- **DSN 里完全没有禁布区**：挖空、天线净空、电机圆都得自己构造/注入，否则 FR 会往禁区里铺线。
- 其它已知缺陷（本项目实测）：板框退化成 5–6 点自交多边形（需补点重排）、
  77/78 个多边形带重复顶点（去重后少 319 个顶点）。
- 导出**必须分块传输**：DSN 有几 MB，桥接单次响应放不下 → 导出器用
  `window.__dsn` 暂存 + `substr` 分块（50KB 一块）取回。

### ② 跑 Freerouting

```bash
python tools/freerouting.py check                       # 查 java / jar / 版本
python tools/freerouting.py run --dsn work/board.dsn --ses work/board.ses \
       --passes 30 --oi 0.25 --threads 8 --poll         # --poll 打印 score/unrouted 进度
```

- **Windows 上必须用 `Start-Process` 语义启动**：把它当"后台作业"挂在本进程下会被中断
  （实测报 `stage interrupted`）。运行器已经按这个语义实现（`subprocess` + 独立进程组 + 日志重定向）。
- 完整参数（FR 2.4.1）：

  | 参数 | 含义 |
  |---|---|
  | `-de <x.dsn>` / `-do <x.ses>` | 输入 DSN / 输出 SES |
  | `-mp <n>` | 最大 pass 数（本项目用 30–40） |
  | `-mt <n>` | 线程数；默认 = 逻辑核数 − 1 |
  | `-oit <f>` | 优化改善阈值（本项目 0.25） |
  | `-us greedy\|global\|hybrid` | 布线策略 |
  | `-is sequential\|random\|prioritized` | 网络排序策略 |
  | `-hr m:n` | 过孔/线成本比 |
  | `-dr <rules>` | 规则文件 |
  | `-l en\|zh` | 日志语言 |

- **FR 不检查孔到孔间距**。它布完看着能通，但两个过孔可能挨得钻不出来 →
  必须用 `python pcbai.py holes` 单独复核（本项目就是靠这一步把 12 处孔距压到合格）。

### ③ 回写 SES：导入器有 4 个坑，导入后必须依次修

```bash
python tools/ses_import.py work/board.ses      # 清空旧铜 → 分块传 SES → importAutoRouteSesFile
python tools/fix_layers.js                     # 坑②：内层铜落到 21/22 层 → 改回 15/16
python tools/restore_widths.py --apply         # 坑①：导入器忽略 SES 里的线宽
python pcbai.py repour                         # 铺铜重灌（每块一次）
# 坑④：新图元不会自动进连通图 → 必须 sync_current_document（一次同步把 519 条悬空降到 37）
```

| # | 导入器的坑 | 症状 | 修法 |
|---|---|---|---|
| ① | 忽略 SES 里的线宽 | 全部变成默认细线 | `restore_widths.py --apply` |
| ② | 内层铜落到 21/22 层 | 内层网络"消失" | `fix_layers.js`（21→15，22→16） |
| ③ | 忽略 SES 的过孔盘径 | 全部 24/12mil，环宽不对 | 按 SES 重建过孔 |
| ④ | 不重建连通图 | 几百条"未连接"假报 | MCP `sync_current_document` |

> 另一条路：MCP 里也有 `eda-copilot-router`（DSL 驱动的内置路由）。
> 但它会往网络规则里注入 `copilot_router_*` 临时规则（本项目注入过 379 条 → DRC 爆 1400 条错误）✗
> 用它就必须**每次跑完清规则**（`tools/reset_netrules.js`）。要稳定可复现，优先走本文的 FR 流水线。

## 3. 判据（改完必须自证）

跑完一轮 FR + 回写，按顺序做这四件事，任何一项不达标就回退：

```bash
python pcbai.py inv            # 每网铜量(线/孔/焊盘) —— 与上一轮基线对比
python pcbai.py drc            # 全量 DRC，违规数只能降不能升
python pcbai.py holes          # 孔到孔/孔径/环宽（FR 不管这个）
python pcbai.py snap           # 板子文本快照，留档以便 diff
```

本项目实测（可作基准）：`-mp 30 -oit 0.25`、6.03mil 间距 + 10.05mil 线宽那一轮，
pass1 = 47 unrouted / 28 violations，最终压到 19 条未布通 → 剩下靠 A\* 与手工补齐。

## 4. 和工具包其它部分的关系

- 几何/A\* 补线：`tools/geom_router.js`（FR 布不通的零散网络靠它）
- 规则与禁布区：`tools/reset_netrules.js`、`tools/mkregion*.py`（本案例的天线禁布区就是这么做出来的）
- 交付：`tools/export_all.py`；案例全过程见 `../case/PIPELINE.md`
