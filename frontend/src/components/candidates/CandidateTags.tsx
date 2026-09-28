import { useEffect, useState } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import Chip from "@mui/material/Chip";
import TextField from "@mui/material/TextField";

import { http } from "../../api/client";
import { useT } from "../../i18n";

// Part 18.10: tags on a candidate (lower-case labels HR adds; filter by them on every list).
export default function CandidateTags({ candidateId, initial, canEdit }: { candidateId: string; initial: string[]; canEdit: boolean }) {
  const t = useT();
  const [tags, setTags] = useState<string[]>(initial);
  const [options, setOptions] = useState<string[]>([]);
  useEffect(() => setTags(initial), [initial]);
  useEffect(() => {
    http.get<{ tag: string }[]>("/api/v1/ui/candidates-tags").then((r) => setOptions(r.map((x) => x.tag))).catch(() => undefined);
  }, []);
  const save = (next: string[]) => {
    const clean = Array.from(new Set(next.map((x) => x.trim().toLowerCase()).filter(Boolean)));
    setTags(clean);
    http.put<{ tags: string[] }>(`/api/v1/ui/candidates/${candidateId}/tags`, { tags: clean }).then((r) => setTags(r.tags)).catch(() => undefined);
  };
  if (!canEdit) return <>{tags.map((x) => <Chip key={x} size="small" label={x} sx={{ mr: 0.5, mb: 0.5 }} />)}</>;
  return (
    <Autocomplete
      multiple freeSolo size="small" options={options} value={tags}
      onChange={(_e, v) => save(v as string[])}
      renderValue={(value, getItemProps) => value.map((option, index) => {
        const { key, ...itemProps } = getItemProps({ index });
        return <Chip key={key} size="small" color="info" label={option} {...itemProps} />;
      })}
      renderInput={(params) => <TextField {...params} label={t("filters.tags")} placeholder={t("tags.add")} />}
    />
  );
}
