// ===========================================================================
// tourbox eltie - PCB placement, revision B
// 2-layer / 1.0mm FR4.  Schematic FROZEN - PCB only.
//
// Mechanical locks (user-specified):
//   SW1..SW13  travel switches / buttons
//   U7 + LED1  scroll-wheel opto pair
//   USB1       USB-C at board edge
//   Motor group {U5, H1}: rigid, may translate as a unit.
//       U5 = AS5600 FOC angle sensor, motor axis through it, 28mm dia body.
//       H1 = 3P motor-phase header, 10.70mm from U5 centre (+Y).
//
// Everything else is on its existing position; only these move/appear:
//   motor group {U5,H1} -> (36.0,60.0) / (36.0,70.7): 46mm clear of the cell
//   BT1 18650 holder    -> bottom side, flush to board.bottom (two end pads)
//   H2 H4 H5            -> out of the battery footprint
//   nRF52840 + 2.4G match + chip antenna -> radio end, away from cell & motor
// ===========================================================================

preserve({
  board: true,
  components: ["C1", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18", "C19",
    "C2", "C20", "C21", "C22", "C23", "C24", "C25", "C26", "C27", "C28", "C29", "C3", "C30",
    "C32", "C33", "C34", "C35", "C36", "C37", "C5", "C6", "C67", "C68", "C69", "C7", "C71",
    "C72", "C73", "C74", "C75", "C76", "C77", "C78", "C79", "C8", "C9", "D1", "H2", "H4",
    "L1", "L8", "LDO1", "LED1", "Q1", "R1", "R10", "R12", "R13", "R14", "R15", "R16", "R17",
    "R18", "R19", "R2", "R20", "R21", "R22", "R23", "R24", "R25", "R26", "R27", "R29",
    "R3", "R30", "R31", "R32", "R33", "R34", "R35", "R37", "R38", "R39", "R4", "R40", "R41",
    "R42", "R43", "R44", "R45", "R46", "R47", "R48", "R49", "R5", "R50", "R51", "R52",
    "R53", "R54", "R6", "R7", "R8", "R9", "SW1", "SW10", "SW11", "SW12", "SW13", "SW2",
    "SW3", "SW4", "SW5", "SW6", "SW7", "SW8", "SW9", "U1", "U10", "U2", "U3", "U4", "U7",
    "U8", "U9", "USB1", "X1"],
});

// --------------------------------------------------------------- blocks ----
block("motor_bot", ["U5"], "sensor", "AS5600 FOC sensor, bottom");
block("motor_top", ["H1"], "connector", "3P motor-phase header, top");
block("battery",   ["BT1"], "power", "18650 holder, bottom, flush to board.bottom");

block("nrf_core",  ["U6"], "rf", "nRF52840 AQFN-73");
block("nrf_dcdc",  ["L2", "L3", "C47", "C48", "C49"], "power",
      "nRF main DC-DC L2/L3 + DEC4 filter",
      { placement: "satellite", attachTo: "nrf_core", anchor: pin("U6", "B3") });
block("nrf_dcch",  ["L4"], "power", "nRF high-voltage DC-DC inductor",
      { placement: "satellite", attachTo: "nrf_core", anchor: pin("U6", "AB2") });
block("nrf_clk32k", ["X2", "C43", "C44"], "rf", "32.768kHz crystal",
      { placement: "satellite", attachTo: "nrf_core", anchor: pin("U6", "D2") });
block("nrf_clk32m", ["X3", "C51", "C52"], "rf", "32MHz crystal",
      { placement: "satellite", attachTo: "nrf_core", anchor: pin("U6", "A23") });
block("nrf_dec",   ["C46","C53","C59","C60","C64","C45","C50","C54","C58","C61","C62"], "rf",
      "nRF VCC_NRF + DEC1/2/3/5 + DECUSB + VBUS decoupling (same-role bank)",
      { placement: "satellite", attachTo: "nrf_core", anchor: pin("U6", "W1"), allowDisconnected: true });
block("rf_match",  ["L6","C55","C56","C57","C65","C66","R28"], "rf", "2.4G pi-match + antenna tuning",
      { allowDisconnected: true });
block("rf_ant",    ["L7"], "rf", "2.4G chip antenna");

block("hdr_spi",   ["H2"], "connector", "10P SPI/ADC expansion", { allowDisconnected: true });
block("hdr_ntc",   ["H4"], "connector", "2P NTC thermistor",     { allowDisconnected: true });
block("hdr_swd",   ["H5"], "connector", "5P SWD debug",          { allowDisconnected: true });
block("pwr_bulk",  ["C63"], "power", "+5V local bulk");

// ---------------------------------------------------------- components ----
// Motor group: rigid translate. Reserve its 28mm body circle.
component("U5").block("motor_bot").role("connector").bottom().fixed({ x: -9.0, y: 22.2, rotate: 180 });
component("H1").block("motor_top").role("connector").top().fixed({ x: -9.0, y: 32.9 });
constraintRegion("motor_body", {
  shape: region.rect({ anchor: anchor("board.center"), width: 30, height: 30,
                       offset: { x: -9.0, y: 22.2 } }),
  allow: { blocks: ["motor_bot","motor_top"] },
});

// Battery
component("BT1").block("battery").role("connector").bottom()
  .edgeMount("bottom", { overhang: 0, face: "any", align: "center" });

// nRF52840 + radio
component("U6").block("nrf_core").role("main_ic").top();
component("L2").block("nrf_dcdc").role("passive").top();
component("L3").block("nrf_dcdc").role("passive").top();
component("L4").block("nrf_dcch").role("passive").top();
component("C47").block("nrf_dcdc").role("decoupling_cap").top();
component("C48").block("nrf_dcdc").role("decoupling_cap").top();
component("C49").block("nrf_dcdc").role("decoupling_cap").top();
component("X2").block("nrf_clk32k").role("crystal").top();
component("X3").block("nrf_clk32m").role("crystal").top();
component("C43").block("nrf_clk32k").role("decoupling_cap").top();
component("C44").block("nrf_clk32k").role("decoupling_cap").top();
component("C51").block("nrf_clk32m").role("decoupling_cap").top();
component("C52").block("nrf_clk32m").role("decoupling_cap").top();
component("C46").block("nrf_dec").role("decoupling_cap").top();
component("C53").block("nrf_dec").role("decoupling_cap").top();
component("C59").block("nrf_dec").role("decoupling_cap").top();
component("C60").block("nrf_dec").role("decoupling_cap").top();
component("C64").block("nrf_dec").role("decoupling_cap").top();
component("C45").block("nrf_dec").role("decoupling_cap").top();
component("C50").block("nrf_dec").role("decoupling_cap").top();
component("C54").block("nrf_dec").role("decoupling_cap").top();
component("C58").block("nrf_dec").role("decoupling_cap").top();
component("C61").block("nrf_dec").role("decoupling_cap").top();
component("C62").block("nrf_dec").role("decoupling_cap").top();
component("L6").block("rf_match").role("passive").top();
component("C55").block("rf_match").role("passive").top();
component("C56").block("rf_match").role("passive").top();
component("C57").block("rf_match").role("passive").top();
component("C65").block("rf_match").role("passive").top();
component("C66").block("rf_match").role("passive").top();
component("R28").block("rf_match").role("passive").top();
// Antenna: board edge, may slide along the edge to find keepout space.
component("L7").block("rf_ant").role("connector").top()
  .edgeMount("right", { overhang: 0, face: "any", align: "end", slide: true });
component("H2").block("hdr_spi").role("connector").top();
component("H4").block("hdr_ntc").role("connector").top();
component("H5").block("hdr_swd").role("connector").top();
component("C63").block("pwr_bulk").role("decoupling_cap").top();

// ------------------------------------------------ electrical placement ----
signalPath("nrf_ant", [
  [pin("U6", "H23"), pin("L6", "1")],
  [pin("L6", "2"),   pin("L7", "1")],
], { priority: "critical", maxDistance: 6, preferFacingPads: true, shape: "straight" });

veryNear(comp("C55"), pin("U6", "H23"), "critical");
veryNear(comp("C56"), pin("U6", "H23"), "critical");
veryNear(comp("C57"), pin("U6", "H23"), "critical");
veryNear(comp("C65"), pin("U6", "H23"), "critical");
veryNear(comp("C66"), pin("L7", "1"),   "critical");
veryNear(comp("R28"), pin("L7", "2"),   "high");
near(block("rf_match"), comp("L7"), "critical");
near(block("nrf_core"), comp("L7"), "high");

// Radio end must clear the steel cell AND the motor magnets.
blockClearance("rf_match", "battery", 30, "critical");
blockClearance("nrf_core", "battery", 30, "critical");
blockClearance("rf_match", "motor_top", 18, "critical");
blockClearance("nrf_core", "motor_top", 18, "critical");

// Motor magnets must clear the steel cell too.
blockClearance("motor_bot", "battery", 25, "critical");

// Headers clear of the battery footprint.
away(comp("H2"), comp("BT1"), "critical");
away(comp("H4"), comp("BT1"), "critical");
away(comp("H5"), comp("BT1"), "high");

// nRF DC-DC switching loop short; crystals short.
veryNear(comp("L2"), pin("U6", "B3"),  "critical");
veryNear(comp("L3"), comp("L2"),       "critical");
veryNear(comp("L4"), pin("U6", "AB2"), "critical");
veryNear(comp("X2"), pin("U6", "D2"),  "high");
veryNear(comp("X3"), pin("U6", "A23"), "high");

capCluster(["C46", "C53", "C59", "C60", "C64"], {
  powerNet: "VCC_NRF", returnNet: "GND", target: pin("U6", "W1"),
  maxRows: 2, maxPerRow: 3, gap: 0.3, priority: "high",
});

solver({ grid: 0.5, ignoredSignals: ["GND"], compactness: "normal", ignoreComponents: ["SW1", "SW2", "SW7"] });
