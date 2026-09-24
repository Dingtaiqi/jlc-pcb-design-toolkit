# -*- coding: utf-8 -*-
"""lcsc_verify.py —— 立创商品页"规格核验器"(离线可用): 打印页面里的结构化字段, 不靠型号猜

用途(换料流程第 3 道关):
    换料时必须核验 CL / ESR / 频率 / 精度 / 封装 是否满足器件手册约束。
    型号里的字母**不可靠** —— 实测把 "FC-135R" 默认成 7pF 是错的, 那颗是 12.5pF。
    所以: 抓页面结构化字段来核验。

用法:
    python tools/lcsc_verify.py --file saved.html            # 解析已保存页面(离线)
    python tools/lcsc_verify.py --url https://item.szlcsc.com/95872.html
    python tools/lcsc_verify.py --file saved.html --fp SMD3215-2P     # 判断封装是否一致
    python tools/lcsc_verify.py --file saved.html --need "Load Capacitance=7pF" --need "ESR<=70k"

四种页面格式都吃(实测):
    国际页 lcsc.com    : <script type="application/ld+json"> + PropertyValue 列表
    国内页 item.szlcsc : __NEXT_DATA__ JSON(parameterName/parameterValue) + meta itemProp
退出码: 0 = 全部 --need 满足; 2 = 有未满足; 1 = 解析失败
"""
import io, json, re, sys, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 中英文规格名互认, 这样 --need 可以一直写英文
ALIAS = {
    'load capacitance': '负载电容',
    'esr': '等效串联电阻',
    'equivalent series resistance': '等效串联电阻',
    'equivalent series resistance(esr)': '等效串联电阻',
    'frequency': '频率',
    'operating temperature': '工作温度',
    'normal temperature frequency tolerance': '常温频差',
    'tolerance': '常温频差',
    'package': '封装',
}


def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def parse(html):
    d = {"props": {}, "price": {}, "raw_ok": False}

    def grab(pat, flags=0):
        m = re.search(pat, html, flags)
        return m.group(1) if m else None

    # ① 国际页: JSON-LD
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            j = json.loads(m.group(1))
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        if j.get("sku") or j.get("mpn"):
            d["sku"] = j.get("sku")
            d["mpn"] = j.get("mpn")
            br = j.get("brand") or j.get("manufacturer") or {}
            d["brand"] = br.get("name") if isinstance(br, dict) else str(br)
            d["description"] = j.get("description")
            off = j.get("offers") or {}
            if isinstance(off, dict):
                d["price"]["value"] = off.get("price")
                d["price"]["currency"] = off.get("priceCurrency")
                d["price"]["availability"] = off.get("availability")
                il = off.get("inventoryLevel")
                if isinstance(il, dict):
                    d["price"]["stock"] = il.get("value")
            d["raw_ok"] = True
            break

    # ② 国际页: PropertyValue 规格
    for m in re.finditer(r'\{"@type":"PropertyValue","name":"(.*?)","value":"(.*?)"\}', html):
        d["props"].setdefault(m.group(1), m.group(2))

    # ③ 国内页: __NEXT_DATA__ 里的 parameterName / parameterValue
    for m in re.finditer(r'"parameterName":"(.*?)","parameterCode".*?"parameterValue":"(.*?)"', html, re.S):
        d["props"].setdefault(m.group(1), m.group(2))

    # ④ 国内页: 任意位置的 JSON 字段 + meta itemProp (与 ① 互补, 谁有就用谁)
    d["sku"] = d.get("sku") or grab(r'"sku":"(C\d+)"') or grab(r'itemProp="sku" content="(C\d+)"')
    d["mpn"] = d.get("mpn") or grab(r'"mpn":"([^"]+)"') or grab(r'itemProp="mpn" content="([^"]+)"')
    d["brand"] = d.get("brand") or grab(r'"brand":\{"@type":"Brand","name":"([^"]+)"') \
        or grab(r'itemProp="brand".*?itemProp="name" content="([^"]+)"', re.S)
    d["description"] = d.get("description") or grab(r'"description":"([^"]{20,600})"') \
        or grab(r'<meta name="description" content="([^"]{20,600})"')
    if not d["price"].get("value"):
        m = re.search(r'"offers":\{"@type":"Offer","priceCurrency":"([A-Z]+)","price":([0-9.]+)', html)
        if m:
            d["price"]["currency"], d["price"]["value"] = m.group(1), m.group(2)
        else:
            v = grab(r'itemProp="price" content="([0-9.]+)"')
            c = grab(r'itemProp="priceCurrency" content="([A-Z]+)"')
            if v: d["price"]["value"] = v
            if c: d["price"]["currency"] = c
    if not d["price"].get("stock"):
        d["price"]["stock"] = grab(r'"inventoryLevel":\{"@type":"QuantitativeValue","value":(\d+)') \
            or grab(r'"stockNumber":(\d+)')

    # ⑤ productRecord: 封装码 / 贴片库标签 / 包装
    m = re.search(r'"productRecord":\{(.*?)\}', html, re.S)
    if m:
        blob = m.group(1)
        for key in ("stockNumber", "encapsulationModel", "smtLabel", "productArrange", "productModel"):
            mm = re.search(r'"%s":\s*("?)([^",}]+)\1' % key, blob)
            if mm:
                d[key] = mm.group(2).strip()

    # ⑥ 国内页 商品编号
    if not d.get("sku"):
        d["sku"] = grab(r'商品编号</dt><dd title="(C\d+)"') or grab(r'>(C\d{5,8})<')

    if d.get("sku") or d.get("mpn") or d["props"]:
        d["raw_ok"] = True
    return d


def find_prop(props, key):
    kl = key.lower().strip()
    alias = ALIAS.get(kl, '')
    for k, v in props.items():
        if kl in k.lower() or (alias and alias in k):
            return v
    return None


def num(s):
    m = re.search(r'([0-9.]+)\s*([kKmMµu]?)', str(s))
    if not m:
        return None
    x = float(m.group(1)); p = m.group(2).lower()
    if p == 'k': x *= 1e3
    elif p == 'm': x *= 1e-3
    return x


def check_needs(props, needs):
    out = []
    for need in needs:
        m = re.match(r'\s*(.+?)\s*(<=|>=|=|<|>)\s*(.+?)\s*$', need)
        if not m:
            out.append((need, None, "条件写错")); continue
        key, op, want = m.group(1), m.group(2), m.group(3)
        hit = find_prop(props, key)
        if hit is None:
            out.append((need, None, "页面里没找到该字段")); continue
        a, b = num(hit), num(want)
        if a is not None and b is not None:
            ok = {"<=": a <= b, ">=": a >= b, "=": abs(a - b) < 1e-9 * max(1.0, b),
                  "<": a < b, ">": a > b}[op]
        else:
            ok = str(want).lower() in str(hit).lower()
        out.append((need, ok, "%s %s" % (key, hit)))
    return out


def main():
    args = sys.argv[1:]
    url = f = fp = None
    needs = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--url' and i + 1 < len(args): url = args[i + 1]; i += 2; continue
        if a == '--file' and i + 1 < len(args): f = args[i + 1]; i += 2; continue
        if a == '--fp' and i + 1 < len(args): fp = args[i + 1]; i += 2; continue
        if a == '--need' and i + 1 < len(args): needs.append(args[i + 1]); i += 2; continue
        print("未知参数:", a); print(__doc__); return 1
    if not url and not f:
        print(__doc__); return 1
    try:
        html = io.open(f, encoding='utf-8', errors='replace').read() if f else fetch(url)
    except Exception as e:
        print("抓取/读取失败:", str(e)[:160]); return 1
    d = parse(html)
    if not d.get("raw_ok"):
        print("解析失败: 页面里没有结构化数据(可能被反爬拦了)  页面大小", len(html)); return 1

    print("=" * 62)
    print("MPN        :", d.get("mpn"))
    print("品牌       :", d.get("brand"))
    print("立创料号   :", d.get("sku"))
    print("封装码     :", d.get("encapsulationModel"), " 贴片库:", d.get("smtLabel"), " 包装:", d.get("productArrange"))
    print("价格       :", d["price"].get("value"), d["price"].get("currency"),
          " 库存:", d["price"].get("stock") or d.get("stockNumber"))
    print("描述       :", (d.get("description") or "")[:200])
    if d["props"]:
        print("结构化规格 :")
        for k, v in d["props"].items():
            print("    %-38s %s" % (k, v))
    if fp and d.get("encapsulationModel"):
        a, b = fp.strip().lower(), str(d["encapsulationModel"]).strip().lower()
        same = a in b or b in a
        print("封装一致性 :", "一致 -> Gerber 无需重出 OK" if same else
              "不一致 -> 必须重布线/重验/重出 Gerber  (%s vs %s)" % (fp, d["encapsulationModel"]))
    rc = 0
    if needs:
        print("约束核验   :")
        for need, ok, got in check_needs(d["props"], needs):
            print("    [%s] %-30s -> %s" % ("OK" if ok else ("??" if ok is None else "NG"), need, got))
            if ok is False:
                rc = 2
    print("=" * 62)
    print("提示: 型号里的字母不可靠(FC-135R 有 7pF 也有 12.5pF 版本), 以本页字段为准")
    return rc


if __name__ == '__main__':
    sys.exit(main())
