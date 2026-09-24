// =====================================================================
// tourbox eltie  --  STAGE 1: routing only  (terminal runRouting)
// Copper pours / GND plane are deliberately NOT declared here: they are a
// separate isolated copper task (stage 2) so that a pour/stitching problem
// cannot block the routing transaction.
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

// ---------- 2. Differential pairs: USB 2.0, 90 ohm ---------------------------
// Logical path U1 -> R7/R8 (series) -> USB1 crosses series resistors, so both
// physical segments carry the same differential intent.
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

// ---------- 3. Matched-length groups ----------------------------------------
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

matchedGroup("PWM", {
  nets: ["PWM_U", "PWM_LU", "PWM_V", "PWM_LV", "PWM_W", "PWM_LW"],
  toleranceMm: 3,
});

matchedGroup("SPI", {
  nets: ["SCLK", "SDI", "SDO"],
  toleranceMm: 5,
});

// ---------- 4. Critical / clock / RF nets -----------------------------------
signalNet("XIN", { priority: "critical", viaPreference: "avoid" });
signalNet("XOUT", { priority: "critical", viaPreference: "avoid" });
signalNet("XL1", { priority: "critical", viaPreference: "avoid" });
signalNet("XL2", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17981", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N17987", { priority: "critical", viaPreference: "avoid" });

// 2.4 GHz antenna chain: U6.ANT - C55/56/57/65 shunt - L6 - C66 shunt - L7
signalNet("RF", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19735", { priority: "critical", viaPreference: "avoid" });
signalNet("$1N19975", { priority: "critical", viaPreference: "avoid" });

// ---------- 5. Motor power stage --------------------------------------------
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

// ---------- 6. Power distribution -------------------------------------------
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

// ---------- 7. Digital buses routed with high attention ---------------------
// I2C (400 kHz) and UART are slow: genuine length matching is meaningless,
// so they get high priority and planar preference instead of a matched group.
signalNet("I2CSCL", { priority: "high", viaPreference: "avoid" });
signalNet("I2CSDA", { priority: "high", viaPreference: "avoid" });
signalNet("UART0_TX", { priority: "high" });
signalNet("UART0_RX", { priority: "high" });

signalNet("SCS0.1", { priority: "high" });
signalNet("SCS0.2", { priority: "high" });

// ---------- 8. Bus-aware grouping -------------------------------------------
busDetect(true);

// ---------- terminal: routing only ------------------------------------------
runRouting();
