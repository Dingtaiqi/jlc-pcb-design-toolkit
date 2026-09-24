// =====================================================================
// tourbox eltie  --  STAGE 9: full clean re-route with REAL current values
//                              and the widened U6 escape
// Terminal: runAll()
//
// Two things changed since the last full route:
//
// 1. POWER RULES CORRECTED. The motor is 330KV, driven at 5 V, with
//    6.5 ohm phase-to-phase resistance, so the stall current is
//        5 V / 6.5 ohm = 0.77 A
//    and each phase carries roughly 0.5 A RMS under sinusoidal FOC. The
//    earlier guess of 4 A was ~5x too high and produced
//        copilot_router_net_66_track -> 1.55 mm
//    which is the widest rule in the design and inflated KRT's whole
//    search geometry (every boxed_in report came back track_width 1.55).
//
// 2. U6 MOVED +4 mm in X. Its left pin-escape corridor grew from ~4.75 mm
//    to ~8.75 mm, which is what XL1 needs (KRT had proved it
//    boxed_in_static after 5001 iterations in the narrow corridor). The
//    2.4 GHz chain was re-pitched to 1.9 mm to stay clear of the antenna
//    keepout, and the decoupling row that U6 moved onto was relocated.
//    Component-level DRC collisions: 0.
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

// ---------- ground ----------------------------------------------------------
plane({
  net: "GND",
  layers: "OUTER",
  region: board(),
  zone: { clearanceMm: 0.3, removeIslandsBelowMm2: 10 },
  stitching: { gridMm: 4, via: "drc-min" },
});

// ---------- replace all existing copper -------------------------------------
clearRouting({ nets: "all", items: ["tracks", "vias"] });

// ---------- USB -------------------------------------------------------------
diffPair("USB_CHIP", {
  positive: "USB_DP",
  negative: "USB_DM",
  impedance: { targetOhm: 90, referenceNet: "GND" },
  maxSkewMm: 0.5,
});
// connector side: two parallel pads per net (A6+B6, A7+B7) make full coupling
// impossible; route as high-priority nets at the verified geometry.
signalNet("DP", { priority: "high", viaPreference: "avoid", trackWidthMm: 0.127 });
signalNet("DM", { priority: "high", viaPreference: "avoid", trackWidthMm: 0.127 });

// ---------- clocks / RF -----------------------------------------------------
signalNet("XIN", { priority: "critical", viaPreference: "avoid" });
signalNet("XOUT", { priority: "critical", viaPreference: "avoid" });
signalNet("XL1", { priority: "critical", viaPreference: "avoid" });
signalNet("XL2", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17981", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17987", { priority: "critical", viaPreference: "avoid" });
signalNet("RF", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19735", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19975", { priority: "critical", viaPreference: "avoid" });

// ---------- motor power stage, REAL currents --------------------------------
// 0.77 A stall / ~0.5 A RMS per phase; ~0.35 mm on 1 oz.
powerNet("U", { maxCurrentA: 1.0, priority: "high" });
powerNet("V", { maxCurrentA: 1.0, priority: "high" });
powerNet("W", { maxCurrentA: 1.0, priority: "high" });
powerNet("PGND", { maxCurrentA: 1.2, priority: "high" });
powerNet("AGND", { maxCurrentA: 0.5, priority: "high" });
powerNet("GND_BK", { maxCurrentA: 0.6 });
powerNet("$1N10661", { maxCurrentA: 0.3 });
powerNet("CP", { maxCurrentA: 0.3 });
powerNet("CPH", { maxCurrentA: 0.3 });
powerNet("CPL", { maxCurrentA: 0.3 });
powerNet("SW_BK", { maxCurrentA: 0.6, priority: "high" });
powerNet("FB_BK", { maxCurrentA: 0.05, viaPreference: "avoid" });
powerNet("AVDD", { maxCurrentA: 0.2, priority: "high" });
powerNet("VREG_AVDD", { maxCurrentA: 0.2 });

// ---------- power distribution: battery -> IP5330 -> rails -------------------
powerNet("$1N31433", { maxCurrentA: 1.5, priority: "high" }); // 1S pack
powerNet("$1N31634", { maxCurrentA: 1.5, priority: "high" });
powerNet("LX", { maxCurrentA: 1.5, priority: "high" });
powerNet("IP+5V", { maxCurrentA: 2.0, priority: "high" });    // USB in
powerNet("+5V", { maxCurrentA: 1.5, priority: "high" });      // motor + logic
powerNet("VCC", { maxCurrentA: 0.8, priority: "high" });
powerNet("1V1", { maxCurrentA: 0.6, priority: "high" });
powerNet("VCC_NRF", { maxCurrentA: 0.3, priority: "high" });
powerNet("VBUS", { maxCurrentA: 0.5, priority: "high" });
powerNet("VBUSG", { maxCurrentA: 0.5 });
powerNet("CC1", { maxCurrentA: 0.3 });
powerNet("CC2", { maxCurrentA: 0.3 });

// ---------- digital, no length matching -------------------------------------
for (const n of ["QSPI_SS", "QSPI_SCLK", "QSPI_SD0", "QSPI_SD1", "QSPI_SD2", "QSPI_SD3"]) {
  signalNet(n, { priority: "high" });
}
for (const n of ["PWM_U", "PWM_LU", "PWM_V", "PWM_LV", "PWM_W", "PWM_LW"]) {
  signalNet(n, { priority: "high" });
}
for (const n of ["SCLK", "SDI", "SDO", "SCS0.1", "SCS0.2"]) {
  signalNet(n, { priority: "high" });
}
signalNet("I2CSCL", { priority: "high", viaPreference: "avoid" });
signalNet("I2CSDA", { priority: "high", viaPreference: "avoid" });
signalNet("UART0_TX", { priority: "high" });
signalNet("UART0_RX", { priority: "high" });
signalNet("ADC1.1", { priority: "normal" });
signalNet("$1N19139", { priority: "normal" });

busDetect(true);

runAll();
