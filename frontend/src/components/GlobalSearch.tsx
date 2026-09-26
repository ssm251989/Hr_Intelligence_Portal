import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Dialog from "@mui/material/Dialog";
import InputAdornment from "@mui/material/InputAdornment";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import ListSubheader from "@mui/material/ListSubheader";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import SearchIcon from "@mui/icons-material/Search";

import { experienceApi } from "../api/client";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";

// Part 14 section 3 / L-N3 + N6 (docs/HRMS_COMPLETE_SPEC.txt): Ctrl/Cmd+K global search over
// people, candidates, jobs, requests/approvals, settings and reports -- permission-scoped on
// the server. Ctrl/Cmd+K is the ONLY keyboard shortcut in the app (N6); the dialog itself is
// fully keyboard-operable (arrows move, Enter opens, Esc closes).

interface SearchItem {
  id: string;
  title: string;
  subtitle?: string | null;
  path: string;
}

interface SearchGroup {
  type: string;
  label_key: string;
  items: SearchItem[];
}

const GROUP_FALLBACK: Record<string, string> = {
  "search.candidates": "Candidates", "search.employees": "People", "search.jobs": "Jobs", "search.requests": "Requests & approvals",
  "search.settings": "Settings", "search.reports": "Reports", "search.pages": "Pages",
};

export interface PageLink {
  label: string;
  path: string;
}

export default function GlobalSearch({ pages }: { pages: PageLink[] }) {
  const navigate = useNavigate();
  const { data } = useMeBootstrap();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [groups, setGroups] = useState<SearchGroup[]>([]);
  const [active, setActive] = useState(0);
  const timer = useRef<number | undefined>(undefined);

  const label = (key: string) => data?.custom_labels?.[key] ?? GROUP_FALLBACK[key] ?? key;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    window.clearTimeout(timer.current);
    const q = query.trim();
    const pageHits = q ? pages.filter((p) => p.label.toLowerCase().includes(q.toLowerCase())).slice(0, 5) : [];
    const pageGroup: SearchGroup[] = pageHits.length ? [{ type: "page", label_key: "search.pages", items: pageHits.map((p) => ({ id: p.path, title: p.label, path: p.path })) }] : [];
    if (q.length < 2) {
      setGroups(pageGroup);
      return;
    }
    timer.current = window.setTimeout(() => {
      experienceApi
        .search(q)
        .then((r) => {
          setGroups([...pageGroup, ...r.groups]);
          setActive(0);
        })
        .catch(() => setGroups(pageGroup));
    }, 200);
  }, [query, pages]);

  const flat = groups.flatMap((g) => g.items);
  const go = (item: SearchItem | undefined) => {
    if (!item) return;
    setOpen(false);
    setQuery("");
    navigate(item.path);
  };

  let index = -1;
  return (
    <>
      <Box
        component="button"
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Search (Ctrl+K)"
        data-tour="global-search"
        sx={(theme) => ({
          flex: "1 1 280px", maxWidth: 460, minWidth: 0, display: "flex", alignItems: "center", gap: 1.25,
          bgcolor: theme.palette.fresh.surface, border: `1px solid ${theme.palette.fresh.line}`, borderRadius: "12px",
          px: 1.75, py: 1.1, color: theme.palette.fresh.muted, font: "inherit", fontSize: 14, cursor: "pointer", textAlign: "left",
          "&:hover": { borderColor: theme.palette.fresh.brand },
          "&:focus-visible": { outline: `2px solid ${theme.palette.fresh.brand}`, outlineOffset: 2 },
        })}
      >
        <SearchIcon fontSize="small" />
        <Box component="span" sx={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>Search people, jobs, requests…</Box>
        <Box component="kbd" sx={(theme) => ({ font: "inherit", fontSize: 11, border: `1px solid ${theme.palette.fresh.line}`, borderRadius: "6px", px: 0.75, display: { xs: "none", sm: "inline" } })}>
          Ctrl K
        </Box>
      </Box>
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm" aria-label="Global search">
        <Box sx={{ p: 2 }}>
          <TextField
            autoFocus
            fullWidth
            placeholder={label("search.placeholder") === "search.placeholder" ? "Search people, candidates, jobs, requests, settings…" : label("search.placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, flat.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                go(flat[active]);
              }
            }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }}
            inputProps={{ "aria-label": "Search", role: "combobox", "aria-expanded": flat.length > 0, "aria-controls": "global-search-results" }}
          />
          <List id="global-search-results" role="listbox" dense sx={{ maxHeight: 420, overflowY: "auto", mt: 1 }}>
            {query.trim().length >= 2 && flat.length === 0 && (
              <Typography color="text.secondary" sx={{ p: 2 }}>{label("search.empty") === "search.empty" ? "Nothing matches. Try fewer letters or a different word." : label("search.empty")}</Typography>
            )}
            {groups.map((group) => (
              <li key={group.type}>
                <ul style={{ padding: 0 }}>
                  <ListSubheader>{label(group.label_key)}</ListSubheader>
                  {group.items.map((item) => {
                    index += 1;
                    const mine = index;
                    return (
                      <ListItemButton key={`${group.type}-${item.id}`} role="option" selected={mine === active} aria-selected={mine === active}
                        onMouseEnter={() => setActive(mine)} onClick={() => go(item)}>
                        <ListItemText primary={item.title} secondary={item.subtitle ?? undefined} />
                      </ListItemButton>
                    );
                  })}
                </ul>
              </li>
            ))}
          </List>
        </Box>
      </Dialog>
    </>
  );
}
