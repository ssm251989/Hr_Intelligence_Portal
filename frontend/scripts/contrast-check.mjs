// Part 18.6: checks that every text/background pair of the Fresh theme is readable
// (WCAG AA 4.5:1 for text, 3:1 for large text / icons). Run: node scripts/contrast-check.mjs
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../src/theme/tokens.ts", import.meta.url), "utf8");
const block = (mode) => {
  const from = src.indexOf(`  ${mode}: {`);
  const body = src.slice(from, src.indexOf("  },", from));
  return Object.fromEntries([...body.matchAll(/(\w+): "(#[0-9A-Fa-f]{6})"/g)].map((x) => [x[1], x[2]]));
};
const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
let bad = 0;
for (const mode of ["light", "dark"]) {
  const t = block(mode);
  const pairs = [
    ["ink", "surface", 4.5], ["ink", "ground", 4.5], ["muted", "surface", 4.5], ["muted", "ground", 4.5], ["ink", "surface2", 4.5],
    ["brandInk", "brand", 4.5], ["brand", "brandSoft", 3], ["coral", "coralSoft", 3], ["sunInk", "sunSoft", 4.5], ["sky", "skySoft", 3],
    ["ok", "okSoft", 3], ["violet", "violetSoft", 3], ["ink", "okSoft", 4.5], ["ink", "coralSoft", 4.5], ["ink", "sunSoft", 4.5], ["ink", "skySoft", 4.5],
  ];
  const out = pairs.map(([fg, bg, need]) => {
    const r = ratio(t[fg], t[bg]);
    if (r < need) bad += 1;
    return `${r < need ? "FAIL" : "ok"} ${fg}/${bg} ${r.toFixed(2)} (>=${need})`;
  });
  console.log(`${mode}:\n  ${out.join("\n  ")}`);
}
console.log(bad ? `contrast: ${bad} pair(s) too low` : "contrast: all pairs OK");
process.exit(bad ? 1 : 0);
