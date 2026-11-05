import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Typography from "@mui/material/Typography";

import { mediaApi, type MediaItem } from "../api/client";
import { useT } from "../i18n";
import Emoji from "./Emoji";
import Illustration from "./Illustration";
import { useReducedMotion } from "./motion";
import { startPageTour } from "./PageTour";

// Part 15 B / L-V4: "Show me how" on each page -- plays the company's 20-40s loop for this
// page (MP4/WebM; GIF only as a fallback because it is heavy). Admins upload them in
// Settings -> Welcome video & tours. With no clip yet, it offers the step-by-step tour.

let mediaCache: Promise<MediaItem[]> | null = null;
function loadMedia(): Promise<MediaItem[]> {
  mediaCache ??= mediaApi.list().catch(() => []);
  return mediaCache;
}
export function refreshMediaCache() {
  mediaCache = null;
}

export default function ShowMeHow({ tourKey }: { tourKey: string }) {
  const reduced = useReducedMotion();
  const t = useT();
  const [open, setOpen] = useState(false);
  const [media, setMedia] = useState<MediaItem[]>([]);

  useEffect(() => {
    loadMedia().then(setMedia);
  }, []);

  const video = media.find((m) => m.key === `tour.${tourKey}` && m.content_type.startsWith("video/"));
  const gif = media.find((m) => m.key === `tour.${tourKey}.gif` || (m.key === `tour.${tourKey}` && m.content_type === "image/gif"));

  return (
    <>
      <Button variant="outlined" onClick={() => setOpen(true)} startIcon={<Emoji name="clapper" size={16} />}>
        {t("howto.button")}
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth aria-labelledby="show-me-how-title">
        <DialogTitle id="show-me-how-title">{t("howto.title")}</DialogTitle>
        <DialogContent>
          {video ? (
            <Box component="video" src={mediaApi.fileUrl(video.key)} autoPlay={!reduced} loop muted playsInline controls
              sx={{ width: "100%", borderRadius: "14px", bgcolor: "black", aspectRatio: "16 / 10" }}>
              {gif && <img src={mediaApi.fileUrl(gif.key)} alt={t("howto.title")} />}
            </Box>
          ) : gif ? (
            <Box component="img" src={mediaApi.fileUrl(gif.key)} alt={t("howto.title")} sx={{ width: "100%", borderRadius: "14px" }} />
          ) : (
            <Box sx={{ textAlign: "center", py: 2 }}>
              <Illustration name="video-tutorial" height={130} />
              <Typography sx={{ mt: 2, fontWeight: 600 }}>{t("howto.none")}</Typography>
              <Typography color="text.secondary">{t("howto.take_tour_hint")}</Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>{t("action.close")}</Button>
          <Button variant="contained" onClick={() => { setOpen(false); startPageTour(tourKey); }}>{t("howto.take_tour")}</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
