// Part 15 B: recolour the unDraw illustrations in src/assets/ill/ to the theme, once, at
// build/setup time. unDraw's accent is already `currentColor` (the <Illustration> wrapper
// sets it to the company brand); here the light neutrals become theme variables so the
// drawings sit correctly on light AND dark cards. Idempotent -- safe to re-run.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const dir = join(import.meta.dirname, "..", "src", "assets", "ill");
const MAP = {
  // floors, shadows, panels -> the hairline/inset colours
  "#e6e6e6": "var(--line)", "#e4e4e4": "var(--line)", "#e5e5e5": "var(--line)", "#ccc": "var(--line)", "#cacaca": "var(--line)",
  "#cbcbcb": "var(--line)", "#dddedf": "var(--line)", "#dedfe0": "var(--line)", "#d6d6e3": "var(--line)", "#d0cde1": "var(--line)",
  "#f2f2f2": "var(--surface-2)", "#f0f0f0": "var(--surface-2)", "#f1f1f1": "var(--surface-2)", "#fafafa": "var(--surface-2)",
  // unDraw's secondary pink accent -> coral
  "#ff6584": "var(--coral)", "#fd6584": "var(--coral)",
};
let changed = 0;
for (const file of readdirSync(dir).filter((f) => f.endsWith(".svg"))) {
  const path = join(dir, file);
  let svg = readFileSync(path, "utf8");
  const before = svg;
  for (const [hex, token] of Object.entries(MAP)) svg = svg.replace(new RegExp(`"${hex}"`, "gi"), `"${token}"`);
  svg = svg.replace(/<svg /, '<svg role="presentation" focusable="false" ').replace(/(<svg[^>]*?) role="presentation" focusable="false"([^>]*role="presentation")/, "$1$2");
  if (svg !== before) {
    writeFileSync(path, svg);
    changed += 1;
  }
}
console.log(`recoloured ${changed} illustrations`);
