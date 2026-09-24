# design/ —— 设计侧输入（本目录内容默认不入库）

工具包里凡是需要"工程数据"的地方，都从这个目录读；但**具体项目的网表/原理图导出属于私密数据，
不跟着工具包外流**（`.gitignore` 里已排除 `design/Net_List.enet`）。

## 放什么

| 文件 | 从哪来 | 谁在用 |
|---|---|---|
| `Net_List.enet` | EasyEDA Pro：PCB 里 `eda.pcb_Net.getNetlist()`，或设计管理器导出网表 | `pcbai.py bomcheck`（工厂 BOM ⇄ 设计 BOM 对账）、`tools/netlist_fetch.py` 的对照基准 |

## 你要用的时候

```bash
# 1) 把自己的网表放进来（文件名保持 Net_List.enet）
cp /path/to/your/Net_List.enet design/

# 2) 取当前 PCB 网表（会覆盖同目录下的 _netlist_pcb.raw.json）
python pcbai.py netlist pcb

# 3) 与工厂 BOM 对账
python pcbai.py bomcheck /path/to/工厂BOM.xlsx
```

## 为什么不入库

- 网表＝**你的产品设计**（器件型号、网络命名、连接关系）。工具包是给别人复用的，不该带着某个具体项目外流。
- 真需要放版本库时，把这一行从 `.gitignore` 删掉即可：

```
design/Net_List.enet
```

> 建议：**私有仓库**随便放；**公开仓库**务必别放（网表能反推出你的电路结构）。
