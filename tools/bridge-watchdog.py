# -*- coding: utf-8 -*-
"""桥接看门狗 —— 解决「EDA 重启后必须手动点一次重新连接」的痛点
作用:
  1) 桥接进程死了 -> 自动拉起
  2) 桥接活着但 EDA 侧未连 -> 打出醒目提示(扩展不会自动重试, 需要你在 EasyEDA 里点一次"重新连接")
  3) 连上后自动报告, 之后进入安静轮询
用法:
  python tools/bridge-watchdog.py                # 常驻(默认 5 秒轮询)
  python tools/bridge-watchdog.py --once         # 只查一次
  python tools/bridge-watchdog.py --no-start     # 不自动拉起桥接
"""
import json, os, subprocess, sys, time, urllib.request

PORT = int(os.environ.get("EDA_BRIDGE_PORT", "49620"))
SKILL = os.path.join(os.path.expanduser("~"), ".dsh", "skills", "easyeda-api", "scripts", "bridge-server.mjs")

def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:" + str(PORT) + "/health", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None

def start_bridge():
    if not os.path.exists(SKILL):
        print("[warn] 找不到桥接脚本:", SKILL); return False
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
    try:
        subprocess.Popen(["node", SKILL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        print("[ok] 已拉起桥接进程:", SKILL); return True
    except Exception as e:
        print("[err] 拉起失败:", str(e)[:80]); return False

def main():
    once = "--once" in sys.argv
    nostart = "--no-start" in sys.argv
    state = None
    while True:
        h = health()
        if h is None:
            if state != "down":
                print("=" * 64)
                print("桥接未运行 (端口 " + str(PORT) + " 无响应)")
                if not nostart: start_bridge()
                else: print("   请手动启动: tools\start-bridge.cmd")
                print("=" * 64)
            state = "down"
        else:
            eda = bool(h.get("edaConnected"))
            if eda:
                if state != "ok":
                    print("[ok] EDA 已连接 (窗口数 " + str(h.get("edaWindowCount")) + ") —— 可以开始干活了")
                state = "ok"
            else:
                if state != "eda_off":
                    print("=" * 64)
                    print("桥接正常, 但 EDA 侧未连接  <<< 就是这个问题")
                    print("原因: run-api-gateway 扩展只在加载那一刻扫端口, 不会自动重试")
                    print("解决(每次 EDA 重启后一次): 在 EasyEDA 里打开该扩展, 点一次「重新连接」")
                    print("更省事的做法: 先跑本看门狗(或 start-bridge.cmd), 再启动 EasyEDA, 多数情况会自动连上")
                    print("=" * 64)
                state = "eda_off"
        if once: break
        time.sleep(5)

if __name__ == "__main__":
    main()
