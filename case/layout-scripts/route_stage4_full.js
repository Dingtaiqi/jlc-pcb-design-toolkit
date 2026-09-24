// =====================================================================
// tourbox eltie  --  STAGE 4: clean full-board routing transaction
// Terminal: runAll()
//
// Why a full re-route instead of more repairs:
//   The first full transaction (stage 1) ran with two handicaps that made
//   its "partial" inevitable and that later repair passes could not undo,
//   because KRT's remaining/repair budget is only ~14 s per transaction:
//     1. no GND zone existed, so KRT excluded the 124-pad GND net entirely
//        and had no solid reference;
//     2. the matched groups were physically impossible (QSPI 2 mm over
//        15 mm traces), and KRT abandons a whole group it cannot verify.
//   Both are now fixed, so the router gets a clean global plan.
//   Copper coverage is only ~8 %, so the board is not globally congested -
//   the failures were local to pin-escape areas.
//
// This deliberately replaces the existing partial copper.
// =====================================================================

stack({
  boardThicknessMm: 1.0,
  fallbackCopperThicknessOz: 1,
  layers: [
    { kind: "copper", name: "TOP", thicknessOz: 1 },
    {
      kind: "dielectric",
      name: "core",
      thicknessMm: 1.0,
      relativePermittivity: 4.4,
      lossTangent: 0.02,
      material: "FR-4",
    },
    { kind: "copper", name: "BOTTOM", thicknessOz: 1 },
  ],
  solderMask: {
    top: { thicknessMm: 0.01, relativePermittivity: 3.8 },
    bottom: { thicknessMm: 0.01, relativePermittivity: 3.8 },
  },
});

// ---------- ground: mandatory reference + motor-driver return --------------
plane({
  net: "GND",
  layers: "OUTER",
  region: board(),
  zone: {
    clearanceMm: 0.3,
    removeIslandsBelowMm2: 10,
  },
  stitching: {
    gridMm: 4,
    via: "drc-min",
  },
});

// ---------- replace the old partial copper ----------------------------------
clearRouting({ nets: "all", items: ["tracks", "vias"] });

// ---------- differential pair that the router already verified --------------
diffPair("USB_CHIP", {
  positive: "USB_DP",
  negative: "USB_DM",
  impedance: { targetOhm: 90, referenceNet: "GND" },
  maxSkewMm: 0.5,
});
// NOTE: DP/DM (R7/R8 -> USB1) are intentionally NOT declared as a diffPair.
// Each USB-C data net owns two parallel pads (A6+B6, A7+B7); forcing full
// coupling made KRT leave one pad of each net open. They are routed as
// high-priority nets at the same geometry the router verified (0.127 mm).
signalNet("DP", { priority: "high", viaPreference: "avoid", trackWidthMm: 0.127 });
signalNet("DM", { priority: "high", viaPreference: "avoid", trackWidthMm: 0.127 });

// ---------- clocks and RF: short, planar, no vias ---------------------------
signalNet("XIN", { priority: "critical", viaPreference: "avoid" });
signalNet("XOUT", { priority: "critical", viaPreference: "avoid" });
signalNet("XL1", { priority: "critical", viaPreference: "avoid" });
signalNet("XL2", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17981", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17987", { priority: "critical", viaPreference: "avoid" });
signalNet("RF", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19735", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19975", { priority: "critical", viaPreference: "avoid" });

// ---------- motor power stage ----------------------------------------------
powerNet("U", { maxCurrentA: 4, priority: "high" });
powerNet("V", { maxCurrentA: 4, priority: "high" });
powerNet("W", { maxCurrentA: 4, priority: "high" });
powerNet("PGND", { maxCurrentA: 4, priority: "high" });
powerNet("AGND", { maxCurrentA: 1, priority: "high" });
powerNet("GND_BK", { maxCurrentA: 1 });
powerNet("$1N10661", { maxCurrentA: 0.5 });
powerNet("CP", { maxCurrentA: 0.5 });
powerNet("CPH", { maxCurrentA: 0.5 });
powerNet("CPL", { maxCurrentA: 0.5 });
powerNet("SW_BK", { maxCurrentA: 0.5, priority: "high" });
powerNet("FB_BK", { maxCurrentA: 0.1, viaPreference: "avoid" });
powerNet("AVDD", { maxCurrentA: 0.5, priority: "high" });
powerNet("VREG_AVDD", { maxCurrentA: 0.5 });

// ---------- power distribution ----------------------------------------------
powerNet("$1N31433", { maxCurrentA: 3, priority: "high" });
powerNet("$1N31634", { maxCurrentA: 3, priority: "high" });
powerNet("LX", { maxCurrentA: 3, priority: "high" });
powerNet("IP+5V", { maxCurrentA: 3, priority: "high" });
powerNet("+5V", { maxCurrentA: 3, priority: "high" });
powerNet("VCC", { maxCurrentA: 2, priority: "high" });
powerNet("1V1", { maxCurrentA: 1.5, priority: "high" });
powerNet("VCC_NRF", { maxCurrentA: 0.5, priority: "high" });
powerNet("VBUS", { maxCurrentA: 1, priority: "high" });
powerNet("VBUSG", { maxCurrentA: 1 });
powerNet("CC1", { maxCurrentA: 0.5 });
powerNet("CC2", { maxCurrentA: 0.5 });

// ---------- digital buses, high priority, NO length matching -----------------
// QSPI at 133 MHz over ~15 mm: a 20 mm spread is ~134 ps, under 2 % of the
// 7.5 ns period - real length matching is not required and declaring it made
// KRT abandon the group. Same reasoning for PWM (motor commutation, tens of
// kHz) and SPI.
for (const n of [
  "QSPI_SS",
  "QSPI_SCLK",
  "QSPI_SD0",
  "QSPI_SD1",
  "QSPI_SD2",
  "QSPI_SD3",
]) {
  signalNet(n, { priority: "high" });
}
for (const n of [
  "PWM_U",
  "PWM_LU",
  "PWM_V",
  "PWM_LV",
  "PWM_W",
  "PWM_LW",
]) {
  signalNet(n, { priority: "high" });
}
for (const n of ["SCLK", "SDI", "SDO", "SCS0.1", "SCS0.2"]) {
  signalNet(n, { priority: "high" });
}
signalNet("I2CSCL", { priority: "high", viaPreference: "avoid" });
signalNet("I2CSDA", { priority: "high", viaPreference: "avoid" });
signalNet("UART0_TX", { priority: "high" });
signalNet("UART0_RX", { priority: "high" });

busDetect(true);

runAll();
