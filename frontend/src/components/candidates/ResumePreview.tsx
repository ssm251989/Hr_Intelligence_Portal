import { useEffect, useRef, useState } from "react";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { candidatesExtraApi } from "../../api/candidatesExtra";
import type { UUID } from "../../api/types";
import { useT } from "../../i18n";
import { EmptyState } from "../../ui-kit";
import { useFresh } from "./stages";

// Part 15.4 C2: the resume shown beside the parsed details. PDFs are drawn page by page
// with pdfjs-dist (lazy-loaded, so the library only downloads when someone opens a
// resume); the bytes come through the authenticated fetchBlob path. Word files and
// external links get a download button instead.

const MAX_PAGES = 5;

export default function ResumePreview({
  candidateId, resumePath, downloading, onDownload,
}: {
  candidateId: UUID;
  resumePath: string | null | undefined;
  downloading: boolean;
  onDownload: () => void;
}) {
  const t = useT();
  const f = useFresh();
  const holder = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "failed">("idle");
  const [pageCount, setPageCount] = useState(0);
  const isPdf = Boolean(resumePath && !/^https?:\/\//.test(resumePath) && resumePath.toLowerCase().endsWith(".pdf"));

  useEffect(() => {
    if (!isPdf) return;
    let cancelled = false;
    setState("loading");
    (async () => {
      try {
        const blob = await candidatesExtraApi.resumeBlob(candidateId);
        if (!blob) throw new Error("no file");
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        const doc = await pdfjs.getDocument({ data: new Uint8Array(await blob.arrayBuffer()) }).promise;
        if (cancelled || !holder.current) return;
        holder.current.innerHTML = "";
        const width = Math.max(280, holder.current.clientWidth || 560);
        const pages = Math.min(doc.numPages, MAX_PAGES);
        for (let n = 1; n <= pages; n += 1) {
          const page = await doc.getPage(n);
          if (cancelled || !holder.current) return;
          const base = page.getViewport({ scale: 1 });
          const scale = width / base.width;
          const viewport = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = "100%";
          canvas.style.display = "block";
          canvas.style.borderRadius = "10px";
          canvas.style.marginBottom = "12px";
          canvas.setAttribute("role", "img");
          canvas.setAttribute("aria-label", t("candidates.resume.page_label", { page: n, count: doc.numPages }));
          holder.current.appendChild(canvas);
          await page.render({ canvas, viewport }).promise;
        }
        if (!cancelled) {
          setPageCount(doc.numPages);
          setState("ready");
        }
      } catch {
        if (!cancelled) setState("failed");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateId, resumePath, isPdf]);

  const downloadButton = (
    <Button variant="outlined" startIcon={<DescriptionOutlinedIcon />} onClick={onDownload} disabled={downloading}>
      {downloading ? t("candidates.resume.downloading") : t("candidates.resume.download")}
    </Button>
  );

  if (!resumePath) {
    return <EmptyState compact illustration="resume" title={t("candidates.resume.none")} />;
  }
  if (!isPdf) {
    return <EmptyState compact illustration="resume" title={t("candidates.resume.not_pdf")} action={downloadButton} />;
  }
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
        <Typography sx={{ color: f.muted, fontSize: 13 }}>
          {state === "ready" && pageCount > MAX_PAGES
            ? t("candidates.resume.first_pages", { shown: MAX_PAGES, count: pageCount })
            : state === "ready"
              ? t("candidates.resume.pages", { count: pageCount })
              : ""}
        </Typography>
        {downloadButton}
      </Stack>
      {state === "loading" && (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 3, justifyContent: "center" }}>
          <CircularProgress size={18} />
          <Typography sx={{ color: f.muted }}>{t("candidates.resume.loading")}</Typography>
        </Stack>
      )}
      {state === "failed" && <Typography sx={{ color: f.muted, py: 2 }}>{t("candidates.resume.failed")}</Typography>}
      <Box ref={holder} sx={{ maxHeight: 720, overflowY: "auto", bgcolor: f.surface2, borderRadius: "12px", p: state === "ready" ? 1.5 : 0, border: state === "ready" ? `1px solid ${f.line}` : "none" }} />
    </Box>
  );
}
