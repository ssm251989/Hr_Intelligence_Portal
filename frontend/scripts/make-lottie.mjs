// Part 15 B: writes the kit's small Lottie animations to src/assets/lottie/ (our own work, no
// licence strings attached). Colours use the default "Fresh" hex values; <FriendlyAnimation>
// swaps them for the company's theme colours at runtime. Re-run after editing:
//   node scripts/make-lottie.mjs
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = join(import.meta.dirname, "..", "src", "assets");
const out = join(root, "lottie");
mkdirSync(out, { recursive: true });

const hex = (h) => [1, 3, 5].map((i) => Math.round((parseInt(h.slice(i, i + 2), 16) / 255) * 1000) / 1000);
const C = { brand: hex("#0E7C66"), coral: hex("#F26B4B"), sun: hex("#F2B233"), sky: hex("#2F6FDE"), soft: hex("#E2F3EE"), line: hex("#E2E8E5"), white: [1, 1, 1], ink: hex("#15211D") };

const ease = { i: { x: [0.33], y: [1] }, o: { x: [0.67], y: [0] } };
const st = (v) => ({ a: 0, k: v });
const kf = (frames) => ({ a: 1, k: frames.map(([t, s], idx) => (idx < frames.length - 1 ? { t, s: Array.isArray(s) ? s : [s], ...ease } : { t, s: Array.isArray(s) ? s : [s] })) });
const tr = (extra = {}) => ({ ty: "tr", p: st([0, 0]), a: st([0, 0]), s: st([100, 100]), r: st(0), o: st(100), sk: st(0), sa: st(0), ...extra });
const fill = (c, o = 100) => ({ ty: "fl", c: st([...c, 1]), o: st(o), r: 1 });
const stroke = (c, w) => ({ ty: "st", c: st([...c, 1]), o: st(100), w: st(w), lc: 2, lj: 2, ml: 4 });
const ellipse = (w, h, p = [0, 0]) => ({ ty: "el", p: st(p), s: st([w, h]), d: 1 });
const rect = (w, h, r = 0, p = [0, 0]) => ({ ty: "rc", p: st(p), s: st([w, h]), r: st(r), d: 1 });
const path = (v, closed = false) => ({ ty: "sh", ks: st({ i: v.map(() => [0, 0]), o: v.map(() => [0, 0]), v, c: closed }) });
const group = (items, t = {}) => ({ ty: "gr", it: [...items, tr(t)] });
const layer = (ind, shapes, ks = {}, op = 600, extra = {}) => ({
  ddd: 0, ind, ty: 4, nm: `l${ind}`, sr: 1, ao: 0, ip: 0, op, st: 0, bm: 0, shapes,
  ks: { o: st(100), r: st(0), p: st([0, 0, 0]), a: st([0, 0, 0]), s: st([100, 100, 100]), ...ks }, ...extra,
});
const anim = (name, w, h, op, layers, assets = []) => ({ v: "5.7.4", fr: 60, ip: 0, op, w, h, nm: name, ddd: 0, assets, layers });

// 1. success tick -- circle pops, tick draws itself (plays once)
const success = anim("success", 120, 120, 60, [
  layer(1, [group([path([[-18, 2], [-5, 15], [20, -12]]), stroke(C.white, 9), { ty: "tm", s: st(0), e: kf([[14, 0], [40, 100]]), o: st(0), m: 1 }])], { p: st([60, 60, 0]) }, 60),
  layer(2, [group([ellipse(92, 92), fill(C.brand)])], { p: st([60, 60, 0]), s: kf([[0, [0, 0, 100]], [14, [112, 112, 100]], [24, [100, 100, 100]]]) }, 60),
  layer(3, [group([ellipse(92, 92), fill(C.soft)])], { p: st([60, 60, 0]), s: kf([[6, [0, 0, 100]], [30, [130, 130, 100]]]), o: kf([[6, 100], [40, 0]]) }, 60),
]);

// 2. loader -- three dots bouncing in turn (loops)
const loader = anim("loader", 120, 48, 60, [0, 1, 2].map((i) => layer(i + 1, [group([ellipse(14, 14), fill([C.brand, C.sky, C.sun][i])])], {
  p: kf([[i * 8, [30 + i * 30, 30, 0]], [i * 8 + 12, [30 + i * 30, 14, 0]], [i * 8 + 24, [30 + i * 30, 30, 0]], [60, [30 + i * 30, 30, 0]]]),
}, 60)));

// 3. confetti -- pieces burst up and flutter down (plays once)
const rand = (seed) => () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
const r = rand(7);
const confetti = anim("confetti", 240, 240, 110, Array.from({ length: 28 }, (_, i) => {
  const x = 120 + (r() - 0.5) * 60, tx = 120 + (r() - 0.5) * 230, peak = 20 + r() * 70, end = 230 + r() * 20, rot = (r() - 0.5) * 900;
  const col = [C.brand, C.coral, C.sun, C.sky][i % 4];
  return layer(i + 1, [group([i % 3 ? rect(8, 13, 2) : ellipse(9, 9), fill(col)])], {
    p: kf([[0, [x, 200, 0]], [28, [(x + tx) / 2, peak, 0]], [110, [tx, end, 0]]]),
    r: kf([[0, 0], [110, rot]]),
    o: kf([[0, 100], [90, 100], [110, 0]]),
  }, 110);
}));

// 4. empty box -- an open box gently bobbing with a sparkle (loops)
const emptyBox = anim("empty-box", 160, 140, 120, [
  layer(1, [group([ellipse(8, 8), fill(C.sun)])], { p: kf([[0, [118, 34, 0]], [60, [122, 26, 0]], [120, [118, 34, 0]]]), o: kf([[0, 30], [60, 100], [120, 30]]) }, 120),
  layer(2, [
    group([path([[-36, -14], [-50, -34], [-6, -30], [0, -14]], true), fill(C.soft)]),
    group([path([[36, -14], [50, -34], [6, -30], [0, -14]], true), fill(C.soft)]),
    group([rect(76, 50, 8, [0, 11]), fill(C.brand)]),
    group([rect(76, 8, 3, [0, -10]), fill(C.ink, 18)]),
  ], { p: kf([[0, [80, 84, 0]], [60, [80, 78, 0]], [120, [80, 84, 0]]]) }, 120),
  layer(3, [group([ellipse(80, 10), fill(C.line)])], { p: st([80, 126, 0]), s: kf([[0, [100, 100, 100]], [60, [88, 100, 100]], [120, [100, 100, 100]]]) }, 120),
]);

// 5. rocket -- hovers with a flickering flame, for "setup complete" (loops)
const rocket = anim("rocket", 140, 160, 90, [
  layer(1, [group([path([[0, 0], [-10, 22], [0, 34], [10, 22]], true), fill(C.sun)])], { p: st([70, 108, 0]), s: kf([[0, [100, 80, 100]], [8, [100, 120, 100]], [16, [100, 85, 100]], [24, [100, 115, 100]], [32, [100, 80, 100]], [90, [100, 100, 100]]]) }, 90),
  layer(2, [
    group([path([[-10, 30], [-24, 44], [-10, 44]], true), fill(C.coral)]),
    group([path([[10, 30], [24, 44], [10, 44]], true), fill(C.coral)]),
    group([ellipse(10, 10, [0, -6]), fill(C.sky)]),
    group([path([[0, -46], [-16, -12], [-14, 44], [14, 44], [16, -12]], true), fill(C.brand)]),
  ], { p: kf([[0, [70, 64, 0]], [45, [70, 56, 0]], [90, [70, 64, 0]]]) }, 90),
]);

// 6. waving hand -- the Fluent 👋 asset, waving like the mockup greeting (loops)
const handSvg = readFileSync(join(root, "emoji", "waving_hand.svg"), "utf8");
const wave = anim("wave", 64, 64, 144, [{
  ddd: 0, ind: 1, ty: 2, nm: "hand", refId: "hand", sr: 1, ao: 0, ip: 0, op: 144, st: 0, bm: 0,
  ks: { o: st(100), p: st([44, 44, 0]), a: st([22, 22, 0]), s: st([100, 100, 100]), r: kf([[0, 0], [14, 14], [29, -8], [43, 14], [58, 0], [144, 0]]) },
}], [{ id: "hand", w: 32, h: 32, u: "", p: `data:image/svg+xml;base64,${Buffer.from(handSvg).toString("base64")}`, e: 1 }]);
wave.layers[0].ks.s = st([200, 200, 100]);
wave.layers[0].ks.a = st([22, 22, 0]);

for (const [name, data] of Object.entries({ success, loader, confetti, "empty-box": emptyBox, rocket, wave })) {
  writeFileSync(join(out, `${name}.json`), JSON.stringify(data));
}
console.log("wrote 6 animations to src/assets/lottie/");
