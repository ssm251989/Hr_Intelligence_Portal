// Part 15.6 (pre-joiner portal): a deliberately simple, honest "auto-crop" for phone photos
// of paper documents. It does NOT straighten or de-warp the page. It:
//   1. shrinks the photo to a small grey-scale copy,
//   2. picks a brightness threshold that splits paper from background (Otsu's method),
//   3. finds the rows/columns where most pixels are "paper" and keeps the biggest block,
//   4. crops the full-size photo to that box (plus a small margin).
// If the result looks unlikely (tiny box, or almost the whole photo) it keeps the original.
// The person always sees before/after and can use the original or retake.

export interface CropResult {
  blob: Blob;
  url: string;
  cropped: boolean;
  width: number;
  height: number;
}

const MAX_SIDE = 2000; // keeps uploads well under the 10 MB limit
const PROBE_SIDE = 240;

function loadImage(file: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("image"));
    };
    img.src = url;
  });
}

function otsu(hist: number[], total: number): number {
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * hist[i];
  let sumB = 0, wB = 0, best = 0, threshold = 128;
  for (let i = 0; i < 256; i++) {
    wB += hist[i];
    if (!wB) continue;
    const wF = total - wB;
    if (!wF) break;
    sumB += i * hist[i];
    const mB = sumB / wB, mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > best) {
      best = between;
      threshold = i;
    }
  }
  return threshold;
}

/** Longest run of indexes whose value is >= min. */
function longestRun(values: number[], min: number): [number, number] | null {
  let best: [number, number] | null = null;
  let start = -1;
  for (let i = 0; i <= values.length; i++) {
    if (i < values.length && values[i] >= min) {
      if (start < 0) start = i;
    } else if (start >= 0) {
      if (!best || i - 1 - start > best[1] - best[0]) best = [start, i - 1];
      start = -1;
    }
  }
  return best;
}

function toBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode"))), "image/jpeg", 0.9));
}

export async function autoCrop(file: Blob): Promise<CropResult> {
  const img = await loadImage(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
  const W = Math.round(img.naturalWidth * scale), H = Math.round(img.naturalHeight * scale);

  // 1-2: small grey copy + threshold
  const ps = Math.min(1, PROBE_SIDE / Math.max(W, H));
  const pw = Math.max(1, Math.round(W * ps)), ph = Math.max(1, Math.round(H * ps));
  const probe = document.createElement("canvas");
  probe.width = pw;
  probe.height = ph;
  const pctx = probe.getContext("2d", { willReadFrequently: true });
  let box: { x: number; y: number; w: number; h: number } | null = null;
  if (pctx) {
    pctx.drawImage(img, 0, 0, pw, ph);
    const px = pctx.getImageData(0, 0, pw, ph).data;
    const grey = new Uint8Array(pw * ph);
    const hist = new Array<number>(256).fill(0);
    for (let i = 0; i < pw * ph; i++) {
      const g = Math.round(0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2]);
      grey[i] = g;
      hist[g]++;
    }
    const th = otsu(hist, pw * ph);
    // 3: share of "paper" pixels per row / column
    const rows = new Array<number>(ph).fill(0), cols = new Array<number>(pw).fill(0);
    for (let y = 0; y < ph; y++) {
      for (let x = 0; x < pw; x++) {
        if (grey[y * pw + x] > th) {
          rows[y]++;
          cols[x]++;
        }
      }
    }
    const r = longestRun(rows.map((v) => v / pw), 0.35);
    const c = longestRun(cols.map((v) => v / ph), 0.35);
    if (r && c) {
      const margin = 0.015;
      const x0 = Math.max(0, c[0] / pw - margin), x1 = Math.min(1, (c[1] + 1) / pw + margin);
      const y0 = Math.max(0, r[0] / ph - margin), y1 = Math.min(1, (r[1] + 1) / ph + margin);
      const area = (x1 - x0) * (y1 - y0);
      if (area > 0.2 && area < 0.92) box = { x: Math.round(x0 * W), y: Math.round(y0 * H), w: Math.round((x1 - x0) * W), h: Math.round((y1 - y0) * H) };
    }
  }

  // 4: draw the (cropped or whole) photo at upload size
  const out = document.createElement("canvas");
  const src = box ?? { x: 0, y: 0, w: W, h: H };
  out.width = src.w;
  out.height = src.h;
  const octx = out.getContext("2d");
  if (!octx) throw new Error("canvas");
  octx.drawImage(img, src.x / scale, src.y / scale, src.w / scale, src.h / scale, 0, 0, src.w, src.h);
  const blob = await toBlob(out);
  return { blob, url: URL.createObjectURL(blob), cropped: Boolean(box), width: src.w, height: src.h };
}

/** The whole photo, just resized (for "use the original"). */
export async function resizeOnly(file: Blob): Promise<CropResult> {
  const img = await loadImage(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
  const out = document.createElement("canvas");
  out.width = Math.round(img.naturalWidth * scale);
  out.height = Math.round(img.naturalHeight * scale);
  const ctx = out.getContext("2d");
  if (!ctx) throw new Error("canvas");
  ctx.drawImage(img, 0, 0, out.width, out.height);
  const blob = await toBlob(out);
  return { blob, url: URL.createObjectURL(blob), cropped: false, width: out.width, height: out.height };
}
