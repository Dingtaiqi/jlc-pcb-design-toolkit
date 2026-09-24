# 标准工作流（每次改动都照这个走）

## 0) 建基线
```bash
python tools/drc_full.py --limit 0     # 记下：唯一违规点数 / 分类
python tools/extract_live.py           # 铜/焊盘快照 live.json
```

## 1) 只改一类东西
用 `tools/*.js` 里的几何脚本（A* 布线段 / 过孔择位 / dogbone / fanout 重布 / 缩宽），
或写新的 JS 用 `python tools/qq.py x.js` 执行。
**一次只改一类**（只布线、或只挪孔、或只改宽），便于归因。

## 2) 自证三连（缺一不可）
```bash
python tools/qq.py tools/repour_once.js      # ① 重灌铜（每块一次）
# ② MCP: sync_current_document  → save + 关标签 + 重开（重建连通图）
python tools/drc_full.py --limit 0           # ③ 全量 DRC（3 pass 去重、100% 覆盖）
```
**保留条件：违规数不增**；连接类改动额外要求「目标网连接错误数下降」。
不满足 → 立刻回滚（用 MCP 检查点，或删除刚建的图元）。

## 3) 存档
`MCP save_checkpoint_for_current_page` —— 每个通过 DRC 的稳定态都存一个。

## 4) 交付
```bash
python tools/export_all.py            # Gerber/BOM/坐标/网表/IPC-356A/PDF/DXF → deliver/
python tools/verify_bom.py            # 工厂 BOM ⇄ 设计 BOM 对账（漏件/数量/值/匹配）
python tools/pull_prices.py           # 立创比价（物料成本基准）
```
预生产检查：最小孔径/环宽/线宽间距/孔到孔 对照板厂工艺档；包内放 `STACKUP_README.txt`。

## 5) 人工介入点（AI 不该自作主张的地方）
- 天线匹配值、机械挖槽尺寸、机构配合 → 由人定
- 板厂 DFM 反馈 → 逐条给出"可忽略/必须坚持"的分类答复
- 任何"放宽规则"的决定 → 必须留痕（说明依据的是板厂的哪条公开规格）

## 原理图改动后怎么办
只要原理图被动过(改值/换料/增删器件/改网络), **先读 `docs/ECO_CHANGE.md`**, 按里面第 0~4 步走:
先判性质(值/换料/换封装) -> 存档三件套 -> 导入变更(人工确认) -> 铜量 diff + DRC 硬验证 -> 交付文件更新。
铁律: **同封装换料 = Gerber 不动; 换封装或改网络 = 必须重布线+重验+重出。**
