# -*- coding: utf-8 -*-
"""freerouting.py —— 开源 Java 自动布线器(Freerouting)的检查 / 安装 / 运行器

为什么需要它：
  * Freerouting 是 GPL-3.0 的三方二进制(JAR 62MB) + 需要 JDK 25(291MB)，不该塞进 git → 按需下载。
  * Windows 上**必须用"独立进程"语义启动**：当成后台作业挂在当前进程下会被中断(实测 stage interrupted)。
  * 跑起来只有日志可看 → 运行器负责重定向日志、按需打印 score/unrouted/violations 进度。

用法:
    python tools/freerouting.py check                       # 查 java / jar / 版本(只读)
    python tools/freerouting.py install [--proxy http://127.0.0.1:7890]
                                                           # 下载 jar 到 tools/freerouting/
    python tools/freerouting.py run --dsn work/board.dsn --ses work/board.ses \
           [--passes 30] [--oi 0.25] [--threads 8] [--strategy hybrid] \
           [--order prioritized] [--wait] [--poll]
"""
import glob, io, os, re, shutil, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "freerouting")            # 本地缓存(gitignored)
JAR_GLOB = [os.path.join(CACHE, "freerouting-*.jar"),
            os.path.join(HERE, "freerouting-*.jar"),
            os.path.join(HERE, "..", "..", "pcb-layout", "tools", "freerouting-*.jar")]
JDK_GLOBS = [os.path.join(CACHE, "jdk*", "bin", "java.exe"),
             os.path.join(HERE, "jdk*", "bin", "java.exe"),
             os.path.join(HERE, "..", "..", "pcb-layout", "tools", "jdk*", "bin", "java.exe")]
JAR_URL = "https://github.com/freerouting/freerouting/releases/download/v{m}/freerouting-{m}.jar"
DEFAULT_VER = "2.4.1"


def find(patterns):
    for p in patterns:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    return None


def find_java():
    j = find(JDK_GLOBS)
    if j:
        return j, "本地 JDK"
    w = shutil.which("java")
    return (w, "PATH 上的 java") if w else (None, None)


def cmd_check():
    jar = find(JAR_GLOB)
    java, where = find_java()
    print("Freerouting jar :", jar or "缺失 ✗")
    print("java           :", ("%s (%s)" % (java, where)) if java else "缺失 ✗")
    if java:
        try:
            r = subprocess.run([java, "-version"], capture_output=True, timeout=60)
            txt = (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
            print("java 版本      :", txt[0] if txt else "?")
        except Exception as e:
            print("java 版本      : 取不到", str(e)[:60])
    if jar:
        print("jar 大小       : %.1f MB" % (os.path.getsize(jar) / 1048576.0))
    if not (jar and java):
        print("\n下一步: python tools/freerouting.py install      (下载 jar)")
        print("        JDK 25 请自行安装(Adoptium Temurin)，或放到 %s/jdk*/" % CACHE)
    return 0 if (jar and java) else 1


def cmd_install(proxy=None, ver=DEFAULT_VER):
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, "freerouting-%s.jar" % ver)
    if os.path.exists(dst):
        print("已存在:", dst); return 0
    url = JAR_URL.format(m=ver)
    print("下载:", url)
    if proxy:
        os.environ["http_proxy"] = os.environ["https_proxy"] = proxy
        print("(经代理 %s)" % proxy)
    try:
        urllib.request.urlretrieve(url, dst)
    except Exception as e:
        print("下载失败:", str(e)[:160])
        print("请手动下载 %s 放到 %s" % (url, CACHE))
        return 1
    print("已下载: %s (%.1f MB)" % (dst, os.path.getsize(dst) / 1048576.0))
    print("注意: 这是 GPL-3.0 三方组件，不要提交进你的业务仓库（本工具包已 gitignore）")
    return 0


def cmd_run(dsn, ses, passes=30, oi=0.25, threads=None, strategy=None, order=None,
            wait=False, poll=False, extra=None):
    jar, java, _ = find(JAR_GLOB), None, None
    java, where = find_java()
    if not jar:  print("找不到 Freerouting jar → 先跑 install"); return 1
    if not java: print("找不到 java(需要 JDK 25+)"); return 1
    if not os.path.exists(dsn): print("找不到 DSN:", dsn); return 1
    os.makedirs(os.path.dirname(os.path.abspath(ses)) or ".", exist_ok=True)
    log = os.path.splitext(ses)[0] + ".fr.log"
    argv = [java, "-jar", jar, "-de", dsn, "-do", ses, "-mp", str(passes), "-oit", str(oi)]
    if threads: argv += ["-mt", str(threads)]
    if strategy: argv += ["-us", strategy]
    if order: argv += ["-is", order]
    if extra: argv += list(extra)
    print("启动:", " ".join('"%s"' % a if " " in a else a for a in argv))
    print("日志:", log)

    # ★ Windows: 独立进程(独立进程组 + 日志重定向), 不能挂在当前进程的后台作业里
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
    with io.open(log, "wb") as lf:
        p = subprocess.Popen(argv, stdout=lf, stderr=subprocess.STDOUT,
                             cwd=os.path.dirname(os.path.abspath(dsn)) or ".", creationflags=flags)
    if not (wait or poll):
        print("已后台启动, PID=%d（FR 跑完会写 %s）" % (p.pid, ses))
        return 0
    t0, last = time.time(), 0
    while True:
        if poll and os.path.exists(log):
            try:
                txt = io.open(log, encoding="utf-8", errors="replace").read()
                m = re.findall(r"(pass\s+\d+.*|score\D+[\d.]+.*|unrouted\D+\d+.*|violations\D+\d+.*)", txt)
                if len(m) > last:
                    for line in m[last:]: print("  ", line.strip()[:120])
                    last = len(m)
            except Exception:
                pass
        if p.poll() is not None:
            print("FR 结束, 退出码 =", p.returncode, " 用时 %.0fs" % (time.time() - t0))
            print("输出:", ses, "存在" if os.path.exists(ses) else "缺失 ✗")
            return 0 if p.returncode == 0 else 1
        time.sleep(5)


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    c = a[0]; rest = a[1:]
    if c == "check":
        return cmd_check()
    if c == "install":
        proxy = None; ver = DEFAULT_VER; i = 0
        while i < len(rest):
            if rest[i] == "--proxy" and i + 1 < len(rest): proxy = rest[i + 1]; i += 2; continue
            if rest[i] == "--version" and i + 1 < len(rest): ver = rest[i + 1]; i += 2; continue
            i += 1
        return cmd_install(proxy, ver)
    if c == "run":
        o = {"passes": 30, "oi": 0.25, "wait": False, "poll": False}
        i = 0
        while i < len(rest):
            k = rest[i]
            if k.startswith("--") and i + 1 < len(rest) and k in ("--dsn", "--ses", "--passes", "--oi", "--threads", "--strategy", "--order"):
                o[k[2:]] = rest[i + 1]; i += 2; continue
            if k == "--wait": o["wait"] = True; i += 1; continue
            if k == "--poll": o["poll"] = True; i += 1; continue
            i += 1
        if not o.get("dsn") or not o.get("ses"):
            print("需要 --dsn 和 --ses"); print(__doc__); return 1
        return cmd_run(o["dsn"], o["ses"], passes=int(o["passes"]), oi=float(o["oi"]),
                       threads=o.get("threads"), strategy=o.get("strategy"),
                       order=o.get("order"), wait=o["wait"], poll=o["poll"])
    print("未知子命令:", c); print(__doc__); return 1


if __name__ == "__main__":
    sys.exit(main())
