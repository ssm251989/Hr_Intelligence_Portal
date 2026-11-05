import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

// Renders a plain-text job description the way candidates read it: a line ending in ":"
// becomes a heading, "- " / "* " / "• " lines become bullets, blank lines split paragraphs.
// Plain text in, React nodes out -- never HTML injection.
export default function JdPreview({ text, empty }: { text: string; empty?: ReactNode }) {
  const f = useTheme().palette.fresh;
  const lines = text.split(/\r?\n/);
  if (!text.trim()) {
    return <Typography sx={{ color: f.muted, fontStyle: "italic" }}>{empty}</Typography>;
  }
  const out: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (key: string) => {
    if (bullets.length === 0) return;
    out.push(
      <Box component="ul" key={`ul-${key}`} sx={{ m: 0, mb: 1.5, pl: 2.5, "& li": { mb: 0.5 } }}>
        {bullets.map((b, i) => <li key={i}>{b}</li>)}
      </Box>,
    );
    bullets = [];
  };
  lines.forEach((raw, i) => {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
      return;
    }
    flush(String(i));
    if (!line) return;
    if (i === 0) {
      out.push(<Typography key={i} variant="h5" component="h3" sx={{ mb: 1 }}>{line}</Typography>);
    } else if (line.endsWith(":") && line.length <= 60) {
      out.push(<Typography key={i} component="h4" sx={{ fontWeight: 700, color: f.brand, mt: 1.5, mb: 0.5 }}>{line.slice(0, -1)}</Typography>);
    } else {
      out.push(<Typography key={i} sx={{ mb: 1 }}>{line}</Typography>);
    }
  });
  flush("end");
  return <Box sx={{ lineHeight: 1.6 }}>{out}</Box>;
}
