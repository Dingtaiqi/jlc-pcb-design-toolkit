# -*- coding: utf-8 -*-
"""pcbai.py —— PCB-AI Toolkit 命令行入口

用法:
  python pcbai.py drc [--limit N]     全量 DRC 导出(3pass 去重)
  python pcbai.py snap                取铜/焊盘/过孔快照 -> live.json
  python pcbai.py repour              重灌铺铜(每块一次)
  python pcbai.py export [keys...]    导出制造文件到 deliver/
  python pcbai.py bomcheck [xlsx]     工厂 BOM ⇄ 设计 BOM 对账
  python pcbai.py prices [xlsx]       立创比价，输出物料成本
  python pcbai.py run <file.js>       在 EasyEDA 里执行 JS(用到 Geometry 会自动注入几何引擎)
  python pcbai.py selftest            跑工具包只读自检(需桥接已连 EDA)
  python pcbai.py holes               全板钻孔可制造性检查(孔到孔/孔径/环宽, 只读)
  python pcbai.py ping                最小探活(EDA 主线程还转不转, 只读)
  python pcbai.py inv                 清点每个网络的铜量 -> _pcb_net_inventory.json
  python pcbai.py invdiff [A] [B]     铜量前后对比(证明导入变更没删铜)
  python pcbai.py netlist pcb|sch     取网表原文(元件属性来源)
  python pcbai.py propsdiff [A] [B]   元件属性 diff(值/厂商/料号变化)
  python pcbai.py bomdiff [A] [B]     BOM 单元格级 diff(换料说明就用它)
  python pcbai.py lcsc --file x.html  立创页面规格核验(CL/ESR/封装/价格/库存)
  python pcbai.py lcsc --url <url> --fp SMD3215-2P --need "Load Capacitance=7pF"
  python pcbai.py watch [--once]      桥接看门狗: 桥接死了自动拉起, EDA 没连会提示你去点重连
  python pcbai.py help

目录约定(别在别处硬编码路径):
  <项目>/design/    设计侧输入(Net_List.enet 等)
  <项目>/deliver/   交付侧输出(gerber/BOM/坐标 ...)
"""
import sys, os, io, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.join(HERE, 'tools')
PY = sys.executable
ENV = dict(os.environ)
ENV["PYTHONUTF8"] = "1"
ENV["PYTHONIOENCODING"] = "utf-8"


def run(*a):
    return subprocess.call([PY] + list(a), cwd=HERE, env=ENV)


def cmd_run(rest):
    """执行 JS；若脚本用到 Geometry 且本身不是引擎，自动把 geom_router.js 前置注入。"""
    if not rest:
        print('需要 js 文件')
        return 1
    f, extra = rest[0], list(rest[1:])
    if not os.path.exists(f):
        print('[err] 找不到脚本:', f)
        return 1
    src = io.open(f, encoding='utf-8-sig').read()
    g = os.path.join(T, 'geom_router.js')
    if 'Geometry' in src and os.path.abspath(f) != os.path.abspath(g) and os.path.exists(g):
        src = io.open(g, encoding='utf-8-sig').read() + '\n;\n' + src
        f = os.path.join(HERE, '_inject_tmp.js')
        io.open(f, 'w', encoding='utf-8').write(src)
        print('[inject] 已前置注入 geom_router.js (几何引擎 + A* + 择孔)')
    return run(os.path.join(T, 'qq.py'), f, *extra)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('help', '-h', '--help'):
        print(__doc__)
        return 0
    c, rest = sys.argv[1], sys.argv[2:]

    if c == 'drc':      return run(os.path.join(T, 'drc_full.py'), *rest)
    if c == 'snap':     return run(os.path.join(T, 'extract_live.py'), *rest)
    if c == 'repour':   return run(os.path.join(T, 'qq.py'), os.path.join(T, 'repour_once.js'))
    if c == 'export':   return run(os.path.join(T, 'export_all.py'), *rest)
    if c == 'bomcheck': return run(os.path.join(T, 'verify_bom.py'), *rest)
    if c == 'prices':   return run(os.path.join(T, 'pull_prices.py'), *rest)
    if c == 'watch':    return run(os.path.join(T, 'bridge-watchdog.py'), *rest)
    if c == 'run':      return cmd_run(rest)
    if c == 'selftest': return cmd_run([os.path.join(T, 'selftest.js')] + rest)
    if c == 'holes':    return cmd_run([os.path.join(T, 'hole_check.js')] + rest)
    if c == 'ping':     return cmd_run([os.path.join(T, 'ping.js')] + rest)
    if c == 'inv':      return run(os.path.join(T, 'net_inventory.py'), *rest)
    if c == 'invdiff':  return run(os.path.join(T, 'net_inventory_diff.py'), *rest)
    if c == 'netlist':  return run(os.path.join(T, 'netlist_fetch.py'), *rest)
    if c == 'propsdiff':return run(os.path.join(T, 'netlist_props_diff.py'), *rest)
    if c == 'bomdiff':  return run(os.path.join(T, 'bom_diff.py'), *rest)
    if c == 'lcsc':     return run(os.path.join(T, 'lcsc_verify.py'), *rest)

    print('未知命令:', c)
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main())
