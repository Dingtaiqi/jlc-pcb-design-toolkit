# tourbox eltie — PCB layout/routing handover

Stand: after the antenna-keepout fix. **Clearance Error = 0, Differential Pair Error = 0.**
Board is placed and ~113/122 nets routed. Remaining work is listed at the bottom.

---

## 1. Where everything lives

| Item | Path |
|---|---|
| Scratch / all scripts | `D:\360Downloads\tourbox\pcb-layout\` |
| Router op artifacts (per run) | `C:\Users\yinsh\AppData\Local\Temp\easyeda-copilot-mcp\copilot-router\pcb-dsl-<id>\` |
| MCP renders | `C:\Users\yinsh\AppData\Local\Temp\easyeda-copilot-mcp\pcbprev-*.png` |
| Bridge helper | `D:\360Downloads\tourbox\pcb-layout\q.sh 'js code'` |
| DRC summariser | `python drc_sum2.py` (prints Clearance + Connection groups) |
| Open-net extractor | `python opennets.py` |
| Via-cleanup helper | `python delvias2.py` (deletes vias that DRC flags, by real 16-hex id) |
| **GND pad fixer** | `python fix_gnd_pads.py` |
| **Repair DSL** | `route_stage7_repair.js` |

Rollback snapshots:
* `pos_backup.json` — all 166 component positions from before any work
* `pos_before_rf.json` — positions from before the 33 RF parts were placed
* MCP checkpoints (newest last): `2oahx9y4va9jn1to` (current) ← `a7hzclqwbkn2xzce`
  ← `esrz58gxf4a96vfp` ← `p9li9qy2b1egxepa` ← `l05d0ig6rpt1so80` ← `0x8g8byjuowz954a`

---

## 2. Two independent toolchains are installed

1. **MCP** `easyeda-copilot-mcp` v1.1.9 (MIT) → `mcp__easyeda__*` tools.
   Mounted in `C:\Users\yinsh\.dsh\profiles\web\cordis.patch.yml`.
2. **Official `eda.*` API** via the `easyeda-api` skill + `run-api-gateway`
   extension + a local bridge on **port 49620**.
   * start bridge: `node <skill>/scripts/bridge-server.mjs`
   * call it: `POST http://localhost:49620/execute  {"code":"..."}`

**The active EasyEDA tab must be the PCB**; a schematic page breaks PCB calls.

---

## 3. Root cause found: the router could not run at all

`eda-copilot-router` v0.3.0 (MIT) wraps **KiCadRoutingTools 0.21.3** (Python) plus
an in-process EasyEDA WASM planner (hybrid backend).

KRT needs a Python with `numpy`, `scipy`, `shapely`. The router tries to
**download** a managed runtime (`python-build-standalone`) — and this machine has
**no internet** (system proxy `127.0.0.1:7890` is listening but times out).
Result: the router hung with ~0 % CPU, no error, forever.

### Fix that made routing work
`discoverSystemPython()` searches `%LOCALAPPDATA%\Programs\Python\Python*`
**before** falling back to PATH. So a suitable interpreter was placed there:

```
C:\Users\yinsh\AppData\Local\Programs\Python\Python310\   (copy of the uv 3.10.19)
    + numpy 2.2.6 / scipy 1.15.3 / shapely 2.1.2 installed
```
Its direct probe now passes, so `preparePythonDependencies` returns `[]` and
nothing is downloaded. **Do not delete this directory** or routing breaks again.

---

## 4. Patched file (needs MCP restart to take effect)

`C:\Users\yinsh\.dsh\mcp\easyeda-copilot\node_modules\eda-copilot-router\package-dist\chunk-FQB5YI4I.js`

```
KRT_MAX_POST_MAIN_REPAIRS           8 -> 24
KRT_MIN_POST_MAIN_REPAIR_BUDGET_MS  15e3 -> 18e4    (15 s -> 180 s)
KRT_MAX_POST_MAIN_REPAIR_BUDGET_MS  6e4  -> 6e5     (60 s -> 600 s)
```

Backup: `chunk-FQB5YI4I.js.orig-bak-1789758572`

**Why:** the repair budget is `min(MAX, max(MIN, ordinaryElapsedMs * RATIO))`.
A scope-limited repair (`onlyNets(...)`) has a tiny `ordinaryElapsedMs`, so it
always sat on the **15 s floor** — which is why KRT kept answering
`KRT_TIMEOUT ... exceeded its 13760/14698/21722 ms timeout`.

ESM caches the module, so **the MCP server must be restarted** for this to apply.

---

## 5. Antenna keepout (fixed — this was a real defect)

Chip antenna `L7` (RFECA3216060A1T, 2.4 GHz). Datasheet: *"Empty Space 8.0 mm x
3.0 mm"*, *"the limited size for ECA3216 is L>30 mm and D>6 mm"*, *"place on the
middle of PCB edge"*.

The GND pour originally buried the antenna. Fixed with a **forbidden region**:

```js
const p = await eda.pcb_MathPolygon.createPolygon(["R", x, y, w, h, 0, 0]);
const c = await eda.pcb_MathPolygon.createComplexPolygon([p]);
await eda.pcb_PrimitiveRegion.create(12 /*MULTI*/, c, [7,6] /*NO_POURS,NO_FILLS*/,
                                     "ANT_KEEPOUT", 0, false);
```

Two traps, both hit and solved:
* the trailing flags must be **numbers** (`0`), not `false` — `false` is not a
  member of `TPCB_PolygonSourceArray`, the factory silently returns `undefined`;
* in `R` mode **Y is the TOP edge (max Y)** and the rectangle grows *downward*.
  The first attempt landed below the antenna.

Current region: **x 84.6 … 90.5 mm, y 31.0 … 39.0 mm**, id `b045853bc1d8bca7`,
name `ANT_KEEPOUT`. Antenna is on bare board, open toward the right edge.

---

## 6. Ground strategy

* `GND` — poured on **both** layers, island removal on, ~464 vias total.
* `AGND` — separate island around `U4` (DRV8316) including its thermal pad (U4.41).
* `PGND`, `GND_BK` — local copper, joined to GND at the net-ties
  `R14 (PGND→GND)`, `R13 (AGND→GND)`, `R12 (GND_BK→PGND)`.
* Never use a board-wide **grid stitching** again: the blind 4 mm grid repeatedly
  dropped vias onto through-hole pads (H2/H4/SW*/CN1/U7/H5), producing 27
  hole-to-hole errors. Use the targeted approach instead.

---

## 7. Impedance result (verified by the router itself)

```
KRT_IMPEDANCE_GEOMETRY_VERIFIED
USB_DM / USB_DP / DP / DM : target 90 ohm -> calculated 86.76 ohm
width 0.127 mm on TOP, coplanar gap 0.152 mm, referenceNet GND, verified: true
```
`DP`/`DM` are routed as ordinary high-priority nets at that width, **not** as a
`diffPair`: each USB-C data net owns two parallel pads (A6+B6, A7+B7), so
forcing full coupling left one pad of each net open.

---

## 8. Lessons that cost the most time

* **Never** judge free space from a render or from component centres — H2 is a
  25.4 mm long header and it was invisible in the first render-based attempt.
  Use real pad bounding boxes (`bbox_mm.json`) and let DRC arbitrate.
* Removing the GND plane to "avoid a hang" removed the **impedance reference**
  → `IMPEDANCE_STACK_INCOMPLETE`. Routing needs the plane declared.
* `runAll()` pours **after** routing, so KRT sees no ground zone
  (`KRT_GROUND_UNPLANNED`). Route **after** a separate `runCopper()` pour if you
  want KRT to know ground exists.
* Matched groups are a **hard gate**: KRT abandons a whole group it cannot
  verify. QSPI at 2 mm over ~15 mm traces is physically wrong anyway
  (133 MHz → 7.5 ns; FR-4 ~6.7 ps/mm → 20 mm ≈ 134 ps ≈ 2 % of a period).
* `clearRouting({nets:"all"})` does **not** remove vias when you list only
  `items:["tracks","vias"]`… verify counts after every transaction.

---

## 9. Remaining work

**A. 8 open nets** (run `route_stage7_repair.js` **after** the MCP restart):
`XL1`, `PGND`, `PWM_LU`, `PWM_LV`, `SDO`, `ADC1.1`, `$1N19139` (+GND by pour)

`XL1` is the hard one — KRT proved it `boxed_in_static` after 5002 iterations,
blocked by `$1N17186 / SWDIO_NRF / $1N17527 / $1N17367 / XL2 / UART0_RX /
VCC_NRF`. `X2` has since been rotated 270° and `C43`/`C44` moved so XL1/XL2 leave
U6 on non-crossing paths, which should unblock it. If it still fails, the
remaining lever is **placement of U6** — the user authorised moving U1/U6 freely.
U6 is at (66, 34) rot 270, which crowds 8 nets onto its left escape.

**B. 26 GND pads the pour cannot reach** — run `python fix_gnd_pads.py`:
`R42_1 R40_1 C2_1 X1_2 X1_4 C59_1 C54_2 C58_2 C50_2 U10_8 U10_10 U10_15 C21_1
U8_27 C76_2 U6_F23 C55_1 USB1_A1 USB1_A12 R46_1 U2_4 U1_62 U1_81 R14_1 U3_4 U7_2`

**C. 220 GND "free copper region" entries** — one pour object (`e6e6`) reported
once per isolated sliver. `removeIslandsBelowMm2: 10` is being approximated to
"remove all isolated islands" by the extension API, yet some survive. Cosmetic-ish
but DRC-visible; likely needs more stitching vias inside the slivers.

**D. Manual, per the user's own instruction** — antenna match tuning (`L6`,
`C55–C57`, `C65`, `C66`, `R28` are placed and left editable).

---

## 10. On GPU / multi-core (asked twice — the evidence)

* **GPU: no.** The router has no GPU backend, and maze routing is a
  priority-queue graph search — branchy, data-dependent, the wrong shape for a
  GPU. More importantly the failures are **proven negatives**
  (`boxed_in_static` after ~5000 iterations), not slow searches.
* **Multi-core: yes, but not inside the maze router.** KRT `route.py` has no
  `--jobs`/`--threads`; rip-up-and-reroute is inherently sequential. The real
  parallel axis is the **candidate portfolio**: one run produces ~30 candidate
  boards and 7 KRT invocations, all executed **sequentially**
  (`for (const candidate of candidates)` ~ line 3352,
  `for (const job of allRepairJobs)` ~ line 5715). They are independent (own
  `.kicad_pcb`, own DRC audit) and could run N-way concurrently → roughly N×
  more candidates explored for the same wall clock, i.e. **better routing**, not
  merely faster.

---

# APPENDED UPDATE — after the MCP restart + budget patch test

## 11. The budget patch works, and it eliminated the timeouts

Stage 7 (`route_stage7_repair.js`) was run after the restart. Compared with
every earlier attempt, these diagnostics **disappeared completely**:

```
KRT_TIMEOUT
KRT_REPAIR_AUDIT_BUDGET_EXHAUSTED
KRT_NONZERO_EXIT
KRT_SUMMARY_MIN_MISSING
KRT_REPAIR_BUDGET... (all)
```

So KRT now gets its full 180 s. The remaining failures are
`KRT_REPAIR_CANDIDATE_REJECTED` *("did not improve its target or regressed a
full-board safety gate")* — i.e. **a search result, not a timeout.** The budget
is no longer the bottleneck; the geometry is.

## 12. PGND was unblocked by splitting the repair batch

KRT searches a repair batch against a single geometry, and the reported
`boxed_in` geometry was

```
{"grid_step": 0.1, "clearance": 0.152, "track_width": 1.55}
```

for *every* boxed-in net, including 0.254 mm signal nets. `1.55` is the
`defaultValue` of `copilot_router_net_66_track` — the widest track rule in the
design, which is the rule my own `powerNet("U"/"V"/"W"/"PGND", {maxCurrentA: 4})`
produced. Mixing PGND with signal nets in one `onlyNets(...)` batch dragged the
whole batch onto that geometry.

Splitting them (`route_stage8a_narrow.js`, signal nets only, explicit
`trackWidthMm: 0.254`) **routed PGND**: open nets 7 → 6.

NOTE: `inspect_net("U")` shows the phase traces are actually laid at **0.225 mm**
— KRT necked them down. So 1.55 mm is a *search* width, not the copper width.
Whether `maxCurrentA: 4` is right for this motor is still an open design
question and it inflates every search; it is worth confirming the real phase
current with the user.

## 13. GND pad recovery tool — imperfect but useful

`fix_gnd_pads.py` took disconnected GND pads from **26 → 13**. Flaw to fix if
reused: it re-places a via for pads that already succeeded, so each good pad can
accumulate several vias. Recovered: R42_1 R40_1 C54_2 C58_2 C50_2 C76_2 U6_F23
C55_1 R46_1 U2_4 U1_81 R14_1 U7_2.

## 14. Exact state at this checkpoint (`zyxhiceq8ykyvdth`)

* 1657 tracks, 481 vias, Clearance Error **0**, Differential Pair Error **0**
* ANT_KEEPOUT present (`b045853bc1d8bca7`)
* **13 GND pads still unreached by the pour**:
  `C59_1 C2_1 C53_1 C21_1 X1_2 X1_4 USB1_A1 USB1_A12 U10_10 U10_15 U8_27 U1_62 U3_4`
* **7 nets still open** (all `boxed_in_static`):
  * `XL1` — U6 left crystal corridor, blocked by
    `UART0_TX, VCC_NRF, $1N17186, UART0_RX, XL2, $1N17429, $1N17367`
  * `SDO` — blocked by `SDI, SCLK, $1N10661, PWM_LW, I2CSCL, SCS0.1`
  * `ADC1.1` — blocked by `V, ADC2.1, ADC0.1, PWM_LW, W, ADC0, $1N10661`
  * `PWM_LU`, `PWM_LV` — blocked by `PWM_U/V/W/LW, XIN, SWDIO, VCC`
  * `$1N19139` — blocked by `VCC_NRF, +5V, $1N19304, VBUS`
  * `PGND` — one pad left (`U4_12`) after stage 8a
* 211 GND "free copper region" entries (one pour object `e6e6`, many slivers)

## 15. What must change next — placement, not the router

Every remaining open net sits in one of two fully-consumed pin-escape areas:

* **U6 (nRF52840) left side** — `rot 270` puts 8 nets on that escape
  (`XL1 XL2 $1N17186 VCC_NRF×2 $1N19139 $1N19304 $1N17367`) while the 32 kHz
  crystal cluster also lives there. The user has authorised moving U1/U6 freely,
  so the fix is to spread these satellites around U6 instead of stacking them on
  one side, or to rotate U6 so the RF pin still faces the antenna while the
  crystal/DC-DC move to a quieter edge.
* **U4 (DRV8316) area** — a VQFN-40 at 0.5 mm pitch whose escapes are consumed;
  `U, V, W` are laid *and* the `+5V`/`VCC` wide rules crowd it. Needs the
  surrounding passives (C23–C26, C27–C30, R9, R12–R16) re-flowed to open
  escapes, and a decision on the real phase current so the wide-net rule stops
  inflating the search geometry.

## 16. Still-pending manual step

Antenna match tuning (`L6`, `C55–C57`, `C65`, `C66`, `R28`) — placed and left
editable by the user's own instruction. The keepout is now correct so the
tuning can actually be done meaningfully.

---

# UPDATE 2 — after the user supplied the real motor data

## 17. The motor data invalidated my power-rule guess

User: **330KV motor, driven at 5 V, 6.5 ohm phase-to-phase.**

```
stall current  = 5 V / 6.5 ohm = 0.77 A
phase RMS      ~ 0.5 A under sinusoidal FOC
```

My original `powerNet("U"/"V"/"W"/"PGND", {maxCurrentA: 4})` was **~5x too
high**. That value created `copilot_router_net_66_track` with `defaultValue
1.55 mm` — the widest rule in the whole design, which is why every
`boxed_in` report came back as `track_width: 1.55`. Corrected values now in
`route_stage9_final.js`: phases/PGND 1.0–1.2 A, +5V 1.5 A, battery 1.5 A,
VCC 0.8 A, 1V1 0.6 A, VCC_NRF 0.3 A.

## 18. The U6 move was tried and REVERTED

`replan_u6.py` / `replan_u6b.py` moved U6 +4 mm in X (left escape 4.75 → 8.75 mm)
and re-pitched the 2.4 GHz chain to 1.9 mm, with component collisions cleaned to
**0**. Stage 9 then re-routed the whole board with the corrected currents.

Result was **worse**: 108 routed / 14 open (vs 113 / 6), because `USB_DP/DM`,
`+5V`, `V`, `AGND`, `PGND` — all previously connected — broke, plus 21 native
DRC violations. The compressed RF chain and the relocated decoupling row appear
to have cost more on the right side than the widened left escape gained.

**Reverted** to checkpoint `zyxhiceq8ykyvdth`, then re-saved as
**`lwbnmmtvw9e9ojbc`**.

Lesson: a full `clearRouting({nets:"all"})` + `runAll()` is high-variance on this
board. Prefer scope-limited repairs, and always checkpoint first.

## 19. Post-restore recovery recipe (needed twice)

After `restore_checkpoint_for_current_page`:

1. Every `eda.pcb_*` call returns **HTTP 500** and MCP DRC times out, even though
   `eda.dmt_Project.getCurrentProjectInfo()` still works. The editor has lost its
   PCB binding.
   **Fix:** `open_document({document_uuid: "a13a9a0e834c40d3a24ee99ae8ff4e1c"})`.
2. DRC then reports ~14 000 bogus Clearance Errors because the restored pours are
   **unfilled**.
   **Fix:** run `repour_gnd.js` (`runCopper()`), then delete the stitching vias it
   lands on through-hole pads with `python delvias2.py`.

## 20. FINAL STATE — checkpoint `lwbnmmtvw9e9ojbc`

* 1657 tracks, 481 vias, GND poured both layers, ANT_KEEPOUT intact
* **Clearance Error = 0**, **Differential Pair Error = 0**
* **7 open nets:**

| net | open pins | KRT verdict / blocker summary |
|---|---|---|
| `XL1` | X2_1, U6_D2 | `boxed_in_static`, 5001 iters — blocked by `UART0_TX VCC_NRF $1N17186 UART0_RX XL2 $1N17429 $1N17367` |
| `SDO` | track e1087, e1057 | `boxed_in_static`, 5009 iters — blocked by `SDI SCLK $1N10661 PWM_LW I2CSCL SCS0.1` |
| `ADC1.1` | U4_39, R23_1 | `boxed_in_static`, 612 iters — blocked by `V ADC2.1 ADC0.1 PWM_LW W ADC0 $1N10661` |
| `PWM_LU` | U4_28, U1_26 | blocked by `PWM_U/V/W/LW XIN SWDIO VCC` |
| `PWM_LV` | U4_30, U1_28 | same corridor |
| `PGND` | U4_12, U4_15 | partially routed; blocked by `+5V U V ADC0.1 W SCS0.1` |
| `$1N19139` | C62_2, U6_AC5 | blocked by `VCC_NRF +5V $1N19304 VBUS` |

* **13 GND pads still unreached by the pour:**
  `C2_1 C21_1 C53_1 C59_1 U10_10 U10_15 U1_62 U3_4 U8_27 USB1_A1 USB1_A12 X1_2 X1_4`
* 211 GND "free copper region" entries (pour object `e6e6`, many slivers)

## 21. What a human should do next

1. `python fix_gnd_pads.py` again — it took 26 → 13; the remaining 13 are in
   tighter pockets and need 2–3 more rounds or manual vias. (Fix its known flaw:
   remove a pad from the work list once it succeeds.)
2. The 7 open nets are a **placement** problem, in two clusters:
   * U6's left edge — 4 pins (`D2 F2 C1 B1`) inside a 1.24 mm band plus `B3`;
     the 32 kHz crystal and the DC-DC both want that corridor.
   * U4's pin field — a VQFN-40 at 0.5 mm pitch whose escapes are consumed.
   Neither can be fixed by router settings; the satellites must be re-flowed
   around a wider corridor (and the U6 attempt above shows it must be done
   *without* compressing the RF chain).
3. Antenna match tuning — manual, by the user's own choice.
