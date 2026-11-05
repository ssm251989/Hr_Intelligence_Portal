import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { BgvDocumentRead } from "../../api/types";
import { BGV_DOC_TYPES } from "../../api/types";
import { useT } from "../../i18n";
import { Emoji, StatusChip } from "../../ui-kit";

// L-B3: one checklist row per document type, each with a status chip (colour + emoji +
// word). L-B4: when the AI reader spots a name / date-of-birth mismatch (or anything it
// isn't sure about) the row says "Needs a look" -- the AI never decides; HR does.

export const DOC_EMOJI: Record<string, string> = { aadhaar: "id_card", pan: "id_card", degree: "graduation", experience: "briefcase" };

function normaliseName(s: string | null | undefined): string[] {
  return (s || "").toLowerCase().replace(/[^a-zऀ-෿ ]/g, " ").split(/\s+/).filter((w) => w.length > 1).sort();
}

/** True when the name read from the document shares no word with the candidate's name. */
export function nameMismatch(docName: string | null | undefined, candidateName: string | null | undefined): boolean {
  const a = normaliseName(docName);
  const b = normaliseName(candidateName);
  if (!a.length || !b.length) return false;
  return !a.some((w) => b.includes(w));
}

export interface MismatchFlag {
  kind: "name" | "dob" | "other";
  text: string;
}

export function mismatchFlags(doc: BgvDocumentRead, candidateName: string | null | undefined, t: (k: string, v?: Record<string, string | number>) => string): MismatchFlag[] {
  const out: MismatchFlag[] = [];
  const v = doc.validator_output;
  if (!v) return out;
  const issues = v.issues || [];
  const nameIssue = issues.find((i) => /name/i.test(i));
  const dobIssue = issues.find((i) => /(dob|date of birth|birth)/i.test(i));
  if (nameIssue) out.push({ kind: "name", text: nameIssue });
  else if (nameMismatch(v.extracted_fields?.name, candidateName))
    out.push({ kind: "name", text: t("bgv.flag.name_differs", { doc: v.extracted_fields?.name || "", candidate: candidateName || "" }) });
  if (dobIssue) out.push({ kind: "dob", text: dobIssue });
  if (!v.matches_expected_type) out.push({ kind: "other", text: t("bgv.flag.wrong_type", { detected: v.doc_type_detected }) });
  issues.filter((i) => i !== nameIssue && i !== dobIssue).forEach((i) => out.push({ kind: "other", text: i }));
  return out;
}

export default function BgvChecklist({
  docs, candidateName, canValidate, busyId, onValidate,
}: {
  docs: BgvDocumentRead[];
  candidateName: string;
  canValidate: boolean;
  busyId: string | null;
  onValidate: (docId: string) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const known = BGV_DOC_TYPES as readonly string[];
  const types = [...known, ...Array.from(new Set(docs.map((d) => d.doc_type))).filter((d) => !known.includes(d))];

  return (
    <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "flex", flexDirection: "column", gap: 1 }} aria-label={t("bgv.checklist.title")}>
      {types.map((type) => {
        const ofType = docs.filter((d) => d.doc_type === type);
        const label = t(`bgv.doc.${type}`) !== `bgv.doc.${type}` ? t(`bgv.doc.${type}`) : type;
        if (ofType.length === 0) {
          return (
            <Box component="li" key={type} sx={{ display: "flex", alignItems: "center", gap: 1.5, p: 1.25, borderRadius: "12px", border: `1px dashed ${f.line}` }}>
              <Emoji name={DOC_EMOJI[type] ?? "page"} size={20} />
              <Typography sx={{ fontWeight: 600, flex: 1 }}>{label}</Typography>
              <StatusChip tone="muted" emoji="hourglass" label={t("bgv.checklist.missing")} />
            </Box>
          );
        }
        return ofType.map((doc) => {
          const flags = mismatchFlags(doc, candidateName, t);
          const needsLook = doc.validation_status === "needs_review" || (flags.length > 0 && doc.validation_status !== "invalid");
          const v = doc.validator_output;
          const fields = v ? [v.extracted_fields.name, v.extracted_fields.id_number, v.extracted_fields.date].filter(Boolean).join(" · ") : "";
          return (
            <Box component="li" key={doc.id} sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface, border: `1px solid ${needsLook ? f.sun : f.line}` }}>
              <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
                <Emoji name={DOC_EMOJI[type] ?? "page"} size={20} />
                <Typography sx={{ fontWeight: 600, flex: 1, minWidth: 140 }}>{label}</Typography>
                {needsLook && doc.validation_status !== "needs_review" ? (
                  <StatusChip status="needs_review" />
                ) : (
                  <StatusChip status={doc.validation_status} />
                )}
                {canValidate && (
                  <Button size="small" variant="outlined" onClick={() => onValidate(doc.id)} disabled={busyId === doc.id} aria-label={t("bgv.checklist.validate_aria", { doc: label })}>
                    {busyId === doc.id ? t("bgv.checklist.validating") : v ? t("bgv.checklist.revalidate") : t("bgv.checklist.validate")}
                  </Button>
                )}
              </Stack>
              {v && (
                <Box sx={{ mt: 1, pl: 4.5 }}>
                  <Typography sx={{ fontSize: 13, color: f.muted }}>
                    {t("bgv.checklist.read_as", { detected: v.doc_type_detected, fields: fields || t("bgv.checklist.no_fields") })}
                  </Typography>
                  {flags.length > 0 && (
                    <Box sx={{ mt: 1, p: 1, borderRadius: "10px", bgcolor: f.sunSoft }} role="note">
                      <Typography sx={{ fontWeight: 700, fontSize: 13, color: f.sunInk, display: "flex", alignItems: "center", gap: 0.5 }}>
                        <Emoji name="eyes" size={14} /> {t("bgv.flag.title")}
                      </Typography>
                      <Box component="ul" sx={{ m: 0, pl: 2.5, fontSize: 13 }}>
                        {flags.map((fl, i) => (
                          <li key={i}>
                            {fl.kind === "name" ? t("bgv.flag.name") : fl.kind === "dob" ? t("bgv.flag.dob") : ""}
                            {fl.text}
                          </li>
                        ))}
                      </Box>
                      <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.5 }}>{t("bgv.flag.hr_decides")}</Typography>
                    </Box>
                  )}
                </Box>
              )}
            </Box>
          );
        });
      })}
    </Box>
  );
}
