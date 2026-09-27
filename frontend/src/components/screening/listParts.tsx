import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { isMissingEndpoint, screeningExtraApi, type ScoreListParams } from "../../api/screeningExtra";
import type { CandidateApplicationRow, CandidatesListPage } from "../../api/types";
import { useT } from "../../i18n";
import { matchScoreDisplay } from "../../utils/screeningScore";
import CandidateAvatar from "../CandidateAvatar";

// N5: 25 rows by default.
export const ROWS_PER_PAGE_OPTIONS = [10, 25, 50, 100];
export const DEFAULT_PAGE_SIZE = 25;
export type SortMode = "score" | "newest";

/**
 * S3: highest score first through the helper endpoint. "Newest first" -- or a server without
 * the helper -- uses the page's original endpoint unchanged (then sorted by score on screen).
 */
export async function loadSortedPage(
  sort: SortMode,
  params: ScoreListParams,
  original: () => Promise<CandidatesListPage>,
): Promise<CandidatesListPage> {
  if (sort === "newest") return original();
  try {
    return await screeningExtraApi.list({ ...params, sort });
  } catch (err) {
    if (!isMissingEndpoint(err)) throw err;
    const page = await original();
    const score = (r: CandidateApplicationRow) => matchScoreDisplay(r).value ?? -1;
    return { ...page, items: [...page.items].sort((a, b) => score(b) - score(a)) };
  }
}

export function CandidateCell({ row }: { row: CandidateApplicationRow }) {
  const t = useT();
  return (
    <Stack direction="row" spacing={1.25} alignItems="center">
      <CandidateAvatar
        candidateId={row.candidate_id}
        photoPath={row.photo_path}
        name={row.candidate_name}
        email={row.candidate_email}
        sx={{ width: 32, height: 32, fontSize: 12 }}
      />
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" fontWeight={700} noWrap>
          {row.candidate_name || t("screening.unnamed")}
        </Typography>
        {row.candidate_email && (
          <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
            {row.candidate_email}
          </Typography>
        )}
      </Box>
    </Stack>
  );
}

export function SortSelect({ value, onChange, id }: { value: SortMode; onChange: (v: SortMode) => void; id: string }) {
  const t = useT();
  return (
    <FormControl size="small" sx={{ minWidth: 190 }}>
      <InputLabel id={`${id}-sort-label`}>{t("screening.sort.label")}</InputLabel>
      <Select labelId={`${id}-sort-label`} label={t("screening.sort.label")} value={value} onChange={(e) => onChange(e.target.value as SortMode)}>
        <MenuItem value="score">{t("screening.sort.score")}</MenuItem>
        <MenuItem value="newest">{t("screening.sort.newest")}</MenuItem>
      </Select>
    </FormControl>
  );
}

export function PaginationFooter({
  id, page, pageSize, total, selected, onPage, onPageSize,
}: {
  id: string;
  page: number;
  pageSize: number;
  total: number;
  selected: number;
  onPage: (p: number) => void;
  onPageSize: (n: number) => void;
}) {
  const t = useT();
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
      <Typography variant="body2" color="text.secondary">
        {selected > 0 ? `${t("screening.selected", { count: selected })} · ` : ""}
        {t("screening.showing", { start, end, count: total })}
      </Typography>
      <Stack direction="row" spacing={2} alignItems="center">
        <FormControl size="small" sx={{ minWidth: 130 }}>
          <InputLabel id={`${id}-rows-per-page-label`}>{t("screening.rows_per_page")}</InputLabel>
          <Select labelId={`${id}-rows-per-page-label`} label={t("screening.rows_per_page")} value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}>
            {ROWS_PER_PAGE_OPTIONS.map((size) => (
              <MenuItem key={size} value={size}>{size}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <Pagination count={pageCount} page={page} onChange={(_e, value) => onPage(value)} size="small" color="primary" />
      </Stack>
    </Stack>
  );
}
