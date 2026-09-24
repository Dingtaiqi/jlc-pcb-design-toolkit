#!/usr/bin/env python
# Two-layer grid A* over the real copper geometry parsed from the DSN.
# Routes one net at a time; every result is DRC-validated afterwards.
import json, math, heapq, io

OBS = r"D:\360Downloads\tourbox\pcb-layout\obstacles.json"
OUT = r"D:\360Downloads\tourbox\pcb-layout\paths.json"

YOFF = 7.2391          # y_dsn = y_easyeda + YOFF
STEP = 0.1             # mm grid
X0, X1 = 0.0, 90.0
Y0, Y1 = -7.2, 82.8
W, H = int((X1 - X0) / STEP) + 1, int((Y1 - Y0) / STEP) + 1

CLEAR = 0.152          # board minimum
TRACKW = 0.254
HALF = TRACKW / 2.0
INFLATE = CLEAR + HALF + 0.05      # extra 50 um margin
VIA_D = 0.61
VIA_R = VIA_D / 2.0

d = json.load(io.open(OBS, encoding="utf-8"))

occ = {1: bytearray(W * H), 2: bytearray(W * H)}
LAYER_ID = {"TopLayer": 1, "BottomLayer": 2}


def gi(x):
    return int(round((x - X0) / STEP))


def gj(y):
    return int(round((y - Y0) / STEP))


def gx(i):
    return X0 + i * STEP


def gy(j):
    return Y0 + j * STEP


def mark_circle(layer, x, y, r, own=False):
    if layer not in occ or own:
        return
    a = occ[layer]
    ri = int(math.ceil(r / STEP))
    ci, cj = gi(x), gj(y)
    for j in range(max(0, cj - ri), min(H - 1, cj + ri) + 1)):
        pass
