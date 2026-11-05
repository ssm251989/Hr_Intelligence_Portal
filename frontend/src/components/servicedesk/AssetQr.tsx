// T5: a QR code per asset + a printable label sheet (browser print -> "Save as PDF").
// The qrcode library is imported lazily so it only loads when a code is drawn.
import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import GlobalStyles from "@mui/material/GlobalStyles";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { Asset } from "../../api/serviceDeskExtra";
import { useT } from "../../i18n";

/** What the code points at: this page, filtered to the asset's tag. */
export function assetUrl(tag: string): string {
  return `${window.location.origin}/assets?tag=${encodeURIComponent(tag)}`;
}

let qrModule: Promise<typeof import("qrcode")> | null = null;
function loadQr() {
  qrModule ??= import("qrcode");
  return qrModule;
}

export function useQrDataUrl(text: string | null, size = 240): { url: string | null; failed: boolean } {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    setUrl(null);
    setFailed(false);
    if (!text) return;
    loadQr()
      .then((m) => ((m as unknown as { default?: typeof m }).default ?? m).toDataURL(text, { width: size, margin: 1, errorCorrectionLevel: "M", color: { dark: "#000000", light: "#FFFFFF" } }))
      .then((u) => alive && setUrl(u))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [text, size]);
  return { url, failed };
}

export function QrImage({ text, size = 240, alt }: { text: string; size?: number; alt: string }) {
  const t = useT();
  const { url, failed } = useQrDataUrl(text, size * 2);
  if (failed) return <Typography role="alert" sx={{ fontSize: 13 }}>{t("assets.qr.failed")}</Typography>;
  if (!url) return <Box sx={{ width: size, height: size, display: "grid", placeItems: "center" }}><CircularProgress size={24} aria-label={t("helpdesk.common.loading")} /></Box>;
  return <Box component="img" src={url} alt={alt} width={size} height={size} sx={{ width: size, height: size, imageRendering: "pixelated", display: "block" }} />;
}

export function QrDialog({ asset, onClose }: { asset: Asset | null; onClose: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { url } = useQrDataUrl(asset ? assetUrl(asset.asset_tag) : null, 600);
  return (
    <Dialog open={Boolean(asset)} onClose={onClose} maxWidth="xs" fullWidth>
      {asset && (
        <>
          <DialogTitle>{t("assets.qr.title", { tag: asset.asset_tag })}</DialogTitle>
          <DialogContent sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1.5 }}>
            <Box sx={{ p: 1.5, bgcolor: "#FFFFFF", borderRadius: "12px", border: `1px solid ${f.line}` }}>
              <QrImage text={assetUrl(asset.asset_tag)} size={220} alt={t("assets.qr.title", { tag: asset.asset_tag })} />
            </Box>
            <Typography sx={{ fontWeight: 800 }}>{asset.asset_tag}</Typography>
            <Typography sx={{ color: f.muted, fontSize: 14, textAlign: "center" }}>{asset.name}</Typography>
            <Typography sx={{ color: f.muted, fontSize: 13, textAlign: "center" }}>{t("assets.qr.hint")}</Typography>
          </DialogContent>
          <DialogActions>
            {url && <Button component="a" href={url} download={`${asset.asset_tag}-qr.png`}>{t("assets.qr.download")}</Button>}
            <Button onClick={onClose} variant="contained">{t("action.close")}</Button>
          </DialogActions>
        </>
      )}
    </Dialog>
  );
}

/** Label grid shown in a dialog; printing hides everything else on the page. */
export function LabelSheetDialog({ assets, open, onClose, categoryLabel }: { assets: Asset[]; open: boolean; onClose: () => void; categoryLabel: (c: string) => string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="lg" aria-labelledby="sd-labels-title">
      <GlobalStyles styles={{
        "@media print": {
          "body *": { visibility: "hidden !important" },
          "#sd-label-sheet, #sd-label-sheet *": { visibility: "visible !important" },
          "#sd-label-sheet": { position: "fixed", left: 0, top: 0, width: "100%", padding: "8mm", background: "#fff" },
          "@page": { size: "A4", margin: "8mm" },
        },
      }} />
      <DialogTitle id="sd-labels-title">{t("assets.labels.title")}</DialogTitle>
      <DialogContent dividers>
        <Typography sx={{ color: f.muted, mb: 2 }}>
          {assets.length ? t("assets.labels.hint", { count: assets.length }) : t("assets.labels.none")}
        </Typography>
        <Box id="sd-label-sheet" sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(62mm, 1fr))", gap: "4mm", bgcolor: "#fff", color: "#000", p: 1, borderRadius: "8px" }}>
          {assets.map((a) => (
            <Box key={a.id} sx={{ border: "1px dashed #999", borderRadius: "6px", p: "3mm", display: "flex", gap: "3mm", alignItems: "center", breakInside: "avoid", pageBreakInside: "avoid" }}>
              <QrImage text={assetUrl(a.asset_tag)} size={86} alt={t("assets.qr.title", { tag: a.asset_tag })} />
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 800, fontSize: 15, color: "#000", fontVariantNumeric: "tabular-nums" }}>{a.asset_tag}</Typography>
                <Typography sx={{ fontSize: 12, color: "#000" }}>{a.name}</Typography>
                <Typography sx={{ fontSize: 11, color: "#444" }}>{categoryLabel(a.category_code)}{a.serial_number ? ` · ${a.serial_number}` : ""}</Typography>
              </Box>
            </Box>
          ))}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.close")}</Button>
        <Button variant="contained" disabled={!assets.length} onClick={() => window.print()}>{t("assets.labels.print")}</Button>
      </DialogActions>
    </Dialog>
  );
}
