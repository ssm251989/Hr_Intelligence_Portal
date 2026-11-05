import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import { useTheme } from "@mui/material/styles";

import type { PublicJobRead } from "../../api/types";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";
import { formatExperienceRange } from "../../utils/experience";

function Fact({ emoji, text }: { emoji: string; text: string }) {
  const f = useTheme().palette.fresh;
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, borderRadius: 999, px: 1.1, py: 0.35, fontSize: 12, fontWeight: 700, bgcolor: f.surface2, border: `1px solid ${f.line}`, color: f.ink }}>
      <Emoji name={emoji} size={14} />
      {text}
    </Box>
  );
}

/** Department / place / experience / education as pill chips with an emoji each. */
export default function JobFacts({ job, extra }: { job: PublicJobRead; extra?: { emoji: string; text: string }[] }) {
  const t = useT();
  const experience = formatExperienceRange(job.experience_min_years, job.experience_max_years);
  const education = [job.education_degree_level, job.education_field].filter(Boolean).join(t("careers.education_in"));
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {job.department && <Fact emoji="building" text={job.department} />}
      {job.location && <Fact emoji="pin" text={job.location} />}
      {experience && <Fact emoji="hourglass" text={experience} />}
      {education && <Fact emoji="graduation" text={education} />}
      {extra?.map((x) => <Fact key={x.text} emoji={x.emoji} text={x.text} />)}
    </Stack>
  );
}
