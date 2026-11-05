import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import ViewColumnOutlinedIcon from "@mui/icons-material/ViewColumnOutlined";
import BookmarkBorderOutlinedIcon from "@mui/icons-material/BookmarkBorderOutlined";
import FileDownloadOutlinedIcon from "@mui/icons-material/FileDownloadOutlined";

import { experienceApi, type SavedViewRow } from "../api/client";
import RefreshButton from "./RefreshButton";

// Part 14 section 5 / L "every list keeps": RefreshButton (existing behaviour), saved
// filters/views (server-side, per user, optionally shared by an admin), column chooser,
// a bulk-actions slot that appears only when rows are selected, and CSV export of what's on
// screen. Lists pass their own state in; this component owns no data.

export interface ListColumn {
  key: string;
  label: string;
}

export interface ListViewState {
  columns: string[];
  filters: Record<string, unknown>;
  sort?: { field: string; dir: "asc" | "desc" }[];
}

interface Props {
  listKey: string;
  columns: ListColumn[];
  state: ListViewState;
  onStateChange: (state: ListViewState) => void;
  rows: Record<string, unknown>[];
  loading: boolean;
  onRefresh: () => void;
  selectedCount?: number;
  bulkActions?: React.ReactNode;
}

function toCsv(columns: ListColumn[], visible: string[], rows: Record<string, unknown>[]): string {
  const cols = columns.filter((c) => visible.includes(c.key));
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.map((c) => esc(c.label)).join(","), ...rows.map((r) => cols.map((c) => esc(r[c.key])).join(","))].join("\n");
}

export default function ListToolbar({ listKey, columns, state, onStateChange, rows, loading, onRefresh, selectedCount = 0, bulkActions }: Props) {
  const [views, setViews] = useState<SavedViewRow[]>([]);
  const [viewsAnchor, setViewsAnchor] = useState<HTMLElement | null>(null);
  const [columnsAnchor, setColumnsAnchor] = useState<HTMLElement | null>(null);
  const [newName, setNewName] = useState("");

  const loadViews = () => experienceApi.views(listKey).then(setViews).catch(() => undefined);
  useEffect(() => {
    loadViews().then(() => undefined);
  }, [listKey]);
  useEffect(() => {
    const preferred = views.find((v) => v.is_default);
    if (preferred) onStateChange({ ...state, ...(preferred.config as Partial<ListViewState>) });
    // apply the default view once when views first load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [views.length]);

  const exportCsv = () => {
    const blob = new Blob([toCsv(columns, state.columns, rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${listKey}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
      {selectedCount > 0 ? (
        <Stack direction="row" spacing={1} alignItems="center" role="toolbar" aria-label="Bulk actions">
          <Typography variant="body2">{selectedCount} selected</Typography>
          {bulkActions}
        </Stack>
      ) : null}
      <Stack direction="row" spacing={1} sx={{ ml: "auto" }}>
        <Button size="small" startIcon={<BookmarkBorderOutlinedIcon />} onClick={(e) => setViewsAnchor(e.currentTarget)} aria-haspopup="menu">Views</Button>
        <Menu anchorEl={viewsAnchor} open={Boolean(viewsAnchor)} onClose={() => setViewsAnchor(null)}>
          {views.length === 0 && <MenuItem disabled>No saved views yet</MenuItem>}
          {views.map((v) => (
            <MenuItem key={v.id} onClick={() => { onStateChange({ ...state, ...(v.config as Partial<ListViewState>) }); setViewsAnchor(null); }}>
              {v.name}{v.is_default ? " (default)" : ""}{v.mine ? "" : " · shared"}
            </MenuItem>
          ))}
          <MenuItem disableRipple onKeyDown={(e) => e.stopPropagation()}>
            <TextField size="small" placeholder="Save current as…" value={newName} onChange={(e) => setNewName(e.target.value)} inputProps={{ "aria-label": "New view name" }} />
            <Button size="small" disabled={!newName.trim()}
              onClick={() => experienceApi.saveView(listKey, { name: newName.trim(), config: state as unknown as Record<string, unknown> }).then(() => { setNewName(""); loadViews(); })}>Save</Button>
          </MenuItem>
        </Menu>
        <Button size="small" startIcon={<ViewColumnOutlinedIcon />} onClick={(e) => setColumnsAnchor(e.currentTarget)} aria-haspopup="menu">Columns</Button>
        <Menu anchorEl={columnsAnchor} open={Boolean(columnsAnchor)} onClose={() => setColumnsAnchor(null)}>
          {columns.map((c) => (
            <MenuItem key={c.key} dense>
              <FormControlLabel label={c.label} control={
                <Checkbox size="small" checked={state.columns.includes(c.key)}
                  onChange={(e) => onStateChange({ ...state, columns: e.target.checked ? [...state.columns, c.key] : state.columns.filter((k) => k !== c.key) })} />
              } />
            </MenuItem>
          ))}
        </Menu>
        <Button size="small" startIcon={<FileDownloadOutlinedIcon />} onClick={exportCsv} disabled={rows.length === 0}>Export</Button>
        <RefreshButton loading={loading} onRefresh={onRefresh} />
      </Stack>
    </Stack>
  );
}
