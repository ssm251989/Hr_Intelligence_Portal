import { useEffect, useState } from "react";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { careersExtraApi, type CareersSite } from "../../api/careersExtra";
import { useT } from "../../i18n";
import { Emoji, hasEmoji } from "../../ui-kit";

let siteCache: Promise<CareersSite> | null = null;

/** The company's own careers intro / benefits / FAQ (A6). Empty until the company fills them in. */
export function useCareersSite(): CareersSite | null {
  const [site, setSite] = useState<CareersSite | null>(null);
  useEffect(() => {
    let alive = true;
    siteCache = siteCache ?? careersExtraApi.site();
    siteCache.then((s) => alive && setSite(s));
    return () => {
      alive = false;
    };
  }, []);
  return site;
}

// Renders nothing when the company hasn't added benefits -- never placeholder wording.
export function BenefitsSection({ site }: { site: CareersSite | null }) {
  const f = useTheme().palette.fresh;
  const t = useT();
  if (!site || site.benefits.length === 0) return null;
  return (
    <Box component="section" aria-labelledby="careers-benefits-title">
      <Typography id="careers-benefits-title" component="h2" sx={{ fontWeight: 800, fontSize: 22, mb: 2 }}>{t("careers.benefits_title")}</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", md: "repeat(3, minmax(0, 1fr))" }, gap: 2 }}>
        {site.benefits.map((b, i) => (
          <Card key={`${b.title}-${i}`} sx={{ p: 2.25 }}>
            <Box sx={{ width: 42, height: 42, borderRadius: "12px", bgcolor: f.brandSoft, display: "grid", placeItems: "center", mb: 1.25 }}>
              <Emoji name={b.emoji && hasEmoji(b.emoji) ? b.emoji : "sparkles"} size={22} />
            </Box>
            <Typography sx={{ fontWeight: 700 }}>{b.title}</Typography>
            {b.body && <Typography sx={{ color: f.muted, mt: 0.5, whiteSpace: "pre-wrap" }}>{b.body}</Typography>}
          </Card>
        ))}
      </Box>
    </Box>
  );
}

export function FaqSection({ site }: { site: CareersSite | null }) {
  const f = useTheme().palette.fresh;
  const t = useT();
  if (!site || site.faq.length === 0) return null;
  return (
    <Box component="section" aria-labelledby="careers-faq-title">
      <Typography id="careers-faq-title" component="h2" sx={{ fontWeight: 800, fontSize: 22, mb: 2 }}>{t("careers.faq_title")}</Typography>
      <Box>
        {site.faq.map((q, i) => (
          <Accordion key={`${q.question}-${i}`} disableGutters sx={{ mb: 1, "&:before": { display: "none" } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />} aria-controls={`faq-${i}-body`} id={`faq-${i}-head`}>
              <Typography sx={{ fontWeight: 700 }}>{q.question}</Typography>
            </AccordionSummary>
            <AccordionDetails id={`faq-${i}-body`}>
              <Typography sx={{ color: f.muted, whiteSpace: "pre-wrap" }}>{q.answer}</Typography>
            </AccordionDetails>
          </Accordion>
        ))}
      </Box>
    </Box>
  );
}
