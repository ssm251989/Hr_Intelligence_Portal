// Part 17.10/17.11: company logo upload -- PNG, JPG, WebP or SVG, a live preview and a
// simple crop (zoom + move, square or wide) before saving. The file goes to the server's media
// store (the storage connection when one is set up) as `brand.logo`; the sidebar, login page,
// careers site, emails and letters read it from the bootstrap's `branding.logo_url`.
import { useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { mediaApi } from "../../api/client";
import { useT } from "../../i18n";
import { Emoji, FriendlyError } from "../../ui-kit";

const TYPES = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"];
const MAX_BYTES = 2 * 1024 * 1024;
const SHAPES = { square: [1, 1], wide: [3, 1] } as const;
type Shape = keyof typeof SHAPES;

function CropDialog({ file, onClose, onDone }: { file: File | null; onClose: () => void; onDone: (out: File) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [shape, setShape] = useState<Shape>("square");
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState({ x: 0.5, y: 0.5 });

  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => setImg(image);
    image.src = url;
    setZoom(1);
    setPos({ x: 0.5, y: 0.5 });
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // the crop box: shape ratio, as large as fits, scaled down by zoom, centred on pos
  const box = () => {
    if (!img) return null;
    const [rw, rh] = SHAPES[shape];
    let w = img.width;
    let h = (w * rh) / rw;
    if (h > img.height) { h = img.height; w = (h * rw) / rh; }
    w /= zoom; h /= zoom;
    const x = Math.min(Math.max(pos.x * img.width - w / 2, 0), img.width - w);
    const y = Math.min(Math.max(pos.y * img.height - h / 2, 0), img.height - h);
    return { x, y, w, h };
  };

  useEffect(() => {
    const c = canvasRef.current;
    const b = box();
    if (!c || !img || !b) return;
    const [rw, rh] = SHAPES[shape];
    c.width = 480;
    c.height = (480 * rh) / rw;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.drawImage(img, b.x, b.y, b.w, b.h, 0, 0, c.width, c.height);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [img, shape, zoom, pos]);

  const save = () => {
    const c = canvasRef.current;
    if (!c || !file) return;
    c.toBlob((blob) => blob && onDone(new File([blob], file.name.replace(/\.\w+$/, "") + ".png", { type: "image/png" })), "image/png");
  };

  return (
    <Dialog open={Boolean(file)} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("logo.crop.title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ToggleButtonGroup size="small" exclusive value={shape} onChange={(_e, v) => v && setShape(v)}>
            <ToggleButton value="square" sx={{ textTransform: "none" }}>{t("logo.crop.square")}</ToggleButton>
            <ToggleButton value="wide" sx={{ textTransform: "none" }}>{t("logo.crop.wide")}</ToggleButton>
          </ToggleButtonGroup>
          <Box sx={{ bgcolor: f.surface2, border: `1px dashed ${f.line}`, borderRadius: "12px", p: 1, display: "grid", placeItems: "center" }}>
            <canvas ref={canvasRef} style={{ maxWidth: "100%", height: "auto", background: "repeating-conic-gradient(#eee 0% 25%, #fff 0% 50%) 50% / 16px 16px" }}
              aria-label={t("logo.crop.preview")} />
          </Box>
          <Box>
            <Typography sx={{ fontSize: 13 }}>{t("logo.crop.zoom")}</Typography>
            <Slider min={1} max={4} step={0.05} value={zoom} onChange={(_e, v) => setZoom(v as number)} aria-label={t("logo.crop.zoom")} />
            <Typography sx={{ fontSize: 13 }}>{t("logo.crop.left_right")}</Typography>
            <Slider min={0} max={1} step={0.01} value={pos.x} onChange={(_e, v) => setPos((p) => ({ ...p, x: v as number }))} aria-label={t("logo.crop.left_right")} />
            <Typography sx={{ fontSize: 13 }}>{t("logo.crop.up_down")}</Typography>
            <Slider min={0} max={1} step={0.01} value={pos.y} onChange={(_e, v) => setPos((p) => ({ ...p, y: v as number }))} aria-label={t("logo.crop.up_down")} />
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={!img}>{t("logo.crop.use")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function LogoUploader({ currentUrl, onSaved }: { currentUrl?: string | null; onSaved: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const inputRef = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState<File | null>(null);
  const [ready, setReady] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) { setPreview(null); return; }
    const url = URL.createObjectURL(ready);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [ready]);

  const choose = (file: File | undefined) => {
    setProblem(null);
    setError(null);
    if (!file) return;
    if (!TYPES.includes(file.type)) { setProblem(t("logo.bad_type")); return; }
    if (file.size > MAX_BYTES) { setProblem(t("logo.too_big")); return; }
    if (file.type === "image/svg+xml") setReady(file); // vector: no crop needed, stays sharp
    else setPicked(file);
  };

  const save = async () => {
    if (!ready) return;
    setSaving(true);
    setError(null);
    try {
      await mediaApi.upload("brand.logo", ready, "Company logo");
      setReady(null);
      onSaved();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };

  const shown = preview ?? currentUrl ?? null;
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Box sx={{ width: 160, height: 72, border: `1px solid ${f.line}`, borderRadius: "12px", bgcolor: f.surface2, display: "grid", placeItems: "center", overflow: "hidden" }}>
          {shown ? <img src={shown} alt={t("logo.preview_alt")} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
            : <Typography sx={{ fontSize: 12, color: f.muted, px: 1, textAlign: "center" }}>{t("logo.none")}</Typography>}
        </Box>
        <Stack spacing={1}>
          <Button variant="outlined" onClick={() => inputRef.current?.click()} startIcon={<Emoji name="camera" size={16} />}>
            {currentUrl || ready ? t("logo.change") : t("logo.upload")}
          </Button>
          {ready && <Button variant="contained" onClick={save} disabled={saving}>{saving ? t("logo.saving") : t("logo.save")}</Button>}
        </Stack>
        <input ref={inputRef} hidden type="file" accept={TYPES.join(",")} onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ""; }} />
      </Stack>
      <Typography sx={{ fontSize: 13, color: f.muted }}>{t("logo.hint")}</Typography>
      {ready && <Typography sx={{ fontSize: 13, color: f.sunInk }}>{t("logo.not_saved")}</Typography>}
      {problem && <Typography role="alert" sx={{ fontSize: 13, color: f.coral }}>{problem}</Typography>}
      {error ? <FriendlyError error={error} compact /> : null}
      <CropDialog file={picked} onClose={() => setPicked(null)} onDone={(out) => { setPicked(null); setReady(out); }} />
    </Stack>
  );
}
