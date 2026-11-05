import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";
import { autoCrop, resizeOnly, type CropResult } from "./autoCrop";

const MAX_BYTES = 10 * 1024 * 1024;

// Phone camera (or file) upload for one document. Photos get the simple auto-crop; the
// person sees the result, can switch back to the whole photo, retake, then upload.
// PDFs are sent as they are.
export default function DocumentCapture({ label, onUpload }: { label: string; onUpload: (file: Blob, filename: string) => Promise<void> }) {
  const f = useTheme().palette.fresh;
  const t = useT();
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [processing, setProcessing] = useState(false);
  const [cropped, setCropped] = useState<CropResult | null>(null);
  const [original, setOriginal] = useState<CropResult | null>(null);
  const [pdf, setPdf] = useState<File | null>(null);
  const [choice, setChoice] = useState<"cropped" | "original">("cropped");
  const [uploading, setUploading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => () => {
    if (cropped) URL.revokeObjectURL(cropped.url);
    if (original) URL.revokeObjectURL(original.url);
  }, [cropped, original]);

  const reset = () => {
    setCropped(null);
    setOriginal(null);
    setPdf(null);
    setProblem(null);
    setChoice("cropped");
  };

  const picked = async (file: File | undefined) => {
    if (!file) return;
    reset();
    if (file.type === "application/pdf") {
      if (file.size > MAX_BYTES) setProblem(t("welcome.upload.too_big"));
      else setPdf(file);
      return;
    }
    if (!file.type.startsWith("image/")) {
      setProblem(t("welcome.upload.bad_type"));
      return;
    }
    setProcessing(true);
    try {
      const [c, o] = await Promise.all([autoCrop(file), resizeOnly(file)]);
      setCropped(c);
      setOriginal(o);
      setChoice(c.cropped ? "cropped" : "original");
    } catch {
      setProblem(t("welcome.upload.cant_read"));
    } finally {
      setProcessing(false);
    }
  };

  const chosen = choice === "cropped" && cropped?.cropped ? cropped : original;

  const send = async () => {
    const blob = pdf ?? chosen?.blob;
    if (!blob) return;
    if (blob.size > MAX_BYTES) {
      setProblem(t("welcome.upload.too_big"));
      return;
    }
    setUploading(true);
    setProblem(null);
    try {
      await onUpload(blob, pdf ? pdf.name : `${label.replace(/[^\w-]+/g, "_").toLowerCase() || "document"}.jpg`);
      reset();
    } catch {
      setProblem(t("welcome.upload.failed"));
    } finally {
      setUploading(false);
    }
  };

  const hasPreview = Boolean(pdf || chosen);

  return (
    <Box>
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { void picked(e.target.files?.[0]); e.target.value = ""; }} />
      <input ref={fileRef} type="file" accept="image/*,application/pdf" hidden onChange={(e) => { void picked(e.target.files?.[0]); e.target.value = ""; }} />

      {!hasPreview && !processing && (
        <Stack spacing={1}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <Button variant="contained" size="large" onClick={() => cameraRef.current?.click()} sx={{ minHeight: 48 }}>
              <Emoji name="camera" size={20} />&nbsp;{t("welcome.upload.camera")}
            </Button>
            <Button variant="outlined" size="large" onClick={() => fileRef.current?.click()} sx={{ minHeight: 48 }}>
              <Emoji name="file_folder" size={20} />&nbsp;{t("welcome.upload.file")}
            </Button>
          </Stack>
          <Typography sx={{ fontSize: 12, color: f.muted }}>{t("welcome.upload.tip")}</Typography>
        </Stack>
      )}

      {processing && (
        <Stack direction="row" spacing={1.5} alignItems="center" role="status">
          <CircularProgress size={22} />
          <Typography>{t("welcome.upload.processing")}</Typography>
        </Stack>
      )}

      {hasPreview && (
        <Stack spacing={1.5}>
          {pdf ? (
            <Typography><Emoji name="page" /> {pdf.name}</Typography>
          ) : chosen && (
            <>
              <Box
                component="img" src={chosen.url} alt={t("welcome.upload.preview_alt", { label })}
                sx={{ width: "100%", maxHeight: 360, objectFit: "contain", borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}
              />
              {cropped?.cropped ? (
                <ToggleButtonGroup exclusive size="small" value={choice} onChange={(_, v) => v && setChoice(v)} aria-label={t("welcome.upload.which")}>
                  <ToggleButton value="cropped">{t("welcome.upload.use_cropped")}</ToggleButton>
                  <ToggleButton value="original">{t("welcome.upload.use_original")}</ToggleButton>
                </ToggleButtonGroup>
              ) : (
                <Typography sx={{ fontSize: 12, color: f.muted }}>{t("welcome.upload.no_crop")}</Typography>
              )}
              <Typography sx={{ fontSize: 12, color: f.muted }}>{t("welcome.upload.check")}</Typography>
            </>
          )}
          <Stack direction="row" spacing={1}>
            <Button variant="contained" size="large" onClick={send} disabled={uploading} sx={{ minHeight: 48 }}>
              {uploading ? t("welcome.upload.sending") : t("welcome.upload.send")}
            </Button>
            <Button variant="outlined" size="large" onClick={() => (pdf ? fileRef : cameraRef).current?.click()} disabled={uploading} sx={{ minHeight: 48 }}>
              {t("welcome.upload.retake")}
            </Button>
          </Stack>
        </Stack>
      )}

      {problem && <Alert severity="warning" sx={{ mt: 1.5 }}>{problem}</Alert>}
    </Box>
  );
}
