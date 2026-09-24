// =====================================================================
// tourbox eltie  --  full-board routing transaction
// 2 copper layers, 1.0 mm FR-4, 1 oz copper (provisional stack)
// Everything below is declared as intent; the router derives geometry.
// Terminal: runAll()  -- rules + layer count + copper + routing
// =====================================================================

// ---------- 1. Physical stack (drives impedance + current-derived width) ----
stack({
  boardThicknessMm: 1.0,
  fallbackCopperThicknessOz: 1,
  layers: [
    { kind: "copper", name: "TOP" },
    {
      kind: "dielectric",
      name: "core",
      thicknessMm: 1.0,
      relativePermittivity: 4.4,
      lossTangent: 0.02,
      material: "FR-4",
    },
    { kind: "copper", name: "BOTTOM" },
  ],
  solderMask: {
    top: { thicknessMm: 0.01, relativePermittivity: 3.8 },
    bottom: { thicknessMm: 0.01, relativePermittivity: 3.8 },
  },
});

// ---------- 2. Ground: GND plane on BOTH copper layers + stitching ----------
plane({
  net: "GND",
  layers: "OUTER",
  region: board(),
  stitching: { gridMm: 3, via: "drc-min" },
});

// ---------- 3. Differential pairs -------------------------------------------
// USB 2.0 high-speed, 90 ohm differential.
// Logical path is U1 -> R7/R8 (series) -> USB1, i.e. it crosses a series
// resistor, so both physical segments carry the same differential intent.
diffPair("USB_CHIP", {
  positive: "USB_DP",
  negative: "USB_DM",
  impedance: { targetOhm: 90 },
  maxSkewMm: 0.5,
});

diffPair("USB_CONN", {
  positive: "DP",
  negative: "DM",
  impedance: { targetOhm: 90 },
  maxSkewMm: 0.5,
});

// ---------- 4. Matched-length groups ----------------------------------------
// QSPI: 133 MHz quad SPI to W25Q128 / APS6404 - matching genuinely required.
matchedGroup("QSPI", {
  nets: [
    "QSPI_SS",
    "QSPI_SCLK",
    "QSPI_SD0",
    "QSPI_SD1",
    "QSPI_SD2",
    "QSPI_SD3",
  ],
  toleranceMm: 2,
});

// PWM: six commutation inputs to the DRV8316 - symmetry between phases.
matchedGroup("PWM", {
  nets: ["PWM_U", "PWM_LU", "PWM_V", "PWM_LV", "PWM_W", "PWM_LW"],
  toleranceMm: 3,
});

// SPI: U1 <-> U4 <-> H2 shared clock/data - loose match is harmless.
matchedGroup("SPI", {
  nets: ["SCLK", "SDI", "SDO"],
  toleranceMm: 5,
});

// ---------- 5. Critical / clock / RF nets -----------------------------------
// Oscillators: short, planar, no vias.
signalNet("XIN", { priority: "critical", viaPreference: "avoid" });
signalNet("XOUT", { priority: "critical", viaPreference: "avoid" });
signalNet("XL1", { priority: "critical", viaPreference: "avoid" });
signalNet("XL2", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17981", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17987", { priority: "critical", viaPreference: "avoid" });

// 2.4 GHz antenna chain: every segment stays planar.
//   U6.ANT - C55/C56/C57/C65 shunt - L6 - C66 shunt - L7 antenna
signalNet("RF", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19735", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19975", { priority: "critical", viaPreference: "avoid" });

// ---------- 6. Motor power stage --------------------------------------------
// DRV8316 three-phase outputs - highest current on the board.
powerNet("U", { maxCurrentA: 4, priority: "high" });
powerNet("V", { maxCurrentA: 4, priority: "high" });
powerNet("W", { maxCurrentA: 4, priority: "high" });

// Power grounds. AGND carries the DRV8316 exposed thermal pad, PGND the
// power-stage return; both join GND at their net-tie resistors.
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

// ---------- 7. Power distribution -------------------------------------------
powerNet("$1N31433", { maxCurrentA: 3, priority: "high" }); // pack -> IP5330 (XT30)
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

// ---------- 8. Digital buses routed with high attention ---------------------
// I2C and UART are slow (400 kHz / low baud) so genuine length matching is
// meaningless for them - they get high routing priority and via avoidance
// instead of a matched-group constraint.
signalNet("I2CSCL", { priority: "high", viaPreference: "avoid" });
signalNet("I2CSDA", { priority: "high", viaPreference: "avoid" });
signalNet("UART0_TX", { priority: "high" });
signalNet("UART0_RX", { priority: "high" });

signalNet("SCS0.1", { priority: "high" });
signalNet("SCS0.2", { priority: "high" });

// ---------- 9. Bus-aware grouping -------------------------------------------
busDetect(true);

// ---------- terminal --------------------------------------------------------
runAll();
