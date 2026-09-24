// 只恢复 TOP 层 GND 铺铜（其余 3 块已存在，不能重复创建）
stack({
  boardThicknessMm: 1.6,
  fallbackCopperThicknessOz: 1,
  layers: [
    { kind: "copper", name: "TOP", thicknessOz: 1 },
    { kind: "dielectric", name: "prepreg1", thicknessMm: 0.2, relativePermittivity: 4.4, lossTangent: 0.02, material: "FR-4" },
    { kind: "copper", name: "INNER_1", thicknessOz: 1 },
    { kind: "dielectric", name: "core", thicknessMm: 1.0, relativePermittivity: 4.4, lossTangent: 0.02, material: "FR-4" },
    { kind: "copper", name: "INNER_2", thicknessOz: 1 },
    { kind: "dielectric", name: "prepreg2", thicknessMm: 0.2, relativePermittivity: 4.4, lossTangent: 0.02, material: "FR-4" },
    { kind: "copper", name: "BOTTOM", thicknessOz: 1 },
  ],
});

plane({
  net: "GND",
  layers: ["TOP"],
  region: board(),
  zone: { clearanceMm: 0.3, removeIslandsBelowMm2: 10 },
});

runCopper();
