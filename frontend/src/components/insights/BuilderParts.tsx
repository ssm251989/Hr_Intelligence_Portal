import { useState, type ReactNode } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import AddIcon from "@mui/icons-material/Add";
import CloseIcon from "@mui/icons-material/Close";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { DatasetField } from "../../api/client";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";

// Part 15.6 R1: the drag pieces of the report builder. Every drag has a keyboard/tap
// alternative -- the (+) button on each field adds it to Columns, Filters or Group by.

export type Zone = "columns" | "filters" | "group";

export const TYPE_EMOJI: Record<string, string> = { str: "label", num: "chart_up", date: "calendar", bool: "check" };

export function FieldPill({ field, onAdd }: { field: DatasetField; onAdd: (zone: Zone) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `field:${field.key}`, data: { field } });
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  return (
    <Box ref={setNodeRef}
      sx={{ display: "flex", alignItems: "center", gap: 0.75, p: "6px 6px 6px 8px", borderRadius: "12px", border: `1px solid ${f.line}`, bgcolor: f.surface2, opacity: isDragging ? 0.4 : 1 }}>
      <Box {...listeners} {...attributes} aria-label={t("builder.drag_field", { name: field.label })} role="button"
        sx={{ display: "flex", alignItems: "center", gap: 0.75, flex: 1, minWidth: 0, cursor: "grab", touchAction: "none", borderRadius: "8px", "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 } }}>
        <DragIndicatorIcon sx={{ fontSize: 16, color: f.muted }} />
        <Emoji name={TYPE_EMOJI[field.type] ?? "label"} size={14} />
        <Typography noWrap sx={{ fontSize: 13, fontWeight: 600 }}>{field.label}</Typography>
      </Box>
      <IconButton size="small" aria-label={t("builder.add_field", { name: field.label })} aria-haspopup="menu" onClick={(e) => setAnchor(e.currentTarget)}>
        <AddIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {(["columns", "filters", "group"] as Zone[]).map((z) => (
          <MenuItem key={z} onClick={() => { setAnchor(null); onAdd(z); }}>{t(`builder.add_to.${z}`)}</MenuItem>
        ))}
      </Menu>
    </Box>
  );
}

export function DragGhost({ label }: { label: string }) {
  const f = useTheme().palette.fresh;
  return (
    <Box sx={{ px: 1.5, py: 0.75, borderRadius: 999, bgcolor: f.brand, color: f.brandInk, fontWeight: 700, fontSize: 13, boxShadow: f.shadowHover, display: "inline-block" }}>
      {label}
    </Box>
  );
}

export function DropZone({ zone, emoji, title, hint, children, empty }: { zone: Zone; emoji: string; title: string; hint: string; children: ReactNode; empty: boolean }) {
  const f = useTheme().palette.fresh;
  const { setNodeRef, isOver } = useDroppable({ id: zone });
  return (
    <Box ref={setNodeRef} data-tour={`builder-${zone}`}
      sx={{ p: 1.5, borderRadius: "14px", border: `2px dashed ${isOver ? f.brand : f.line}`, bgcolor: isOver ? f.brandSoft : "transparent", minHeight: 84, transition: "background-color .15s, border-color .15s" }}>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 1 }}>
        <Emoji name={emoji} size={16} />
        <Typography component="h3" sx={{ fontWeight: 800, fontSize: 14 }}>{title}</Typography>
      </Stack>
      {empty ? <Typography sx={{ color: f.muted, fontSize: 13 }}>{hint}</Typography> : <Stack direction="row" flexWrap="wrap" gap={1}>{children}</Stack>}
    </Box>
  );
}

export function ZoneChip({ label, onRemove, children }: { label: string; onRemove: () => void; children?: ReactNode }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  return (
    <Box sx={{ display: "inline-flex", alignItems: "center", gap: 0.75, pl: 1.25, pr: 0.25, py: 0.25, borderRadius: 999, bgcolor: f.brandSoft, color: f.ink, fontSize: 13, fontWeight: 700, flexWrap: "wrap" }}>
      {label}
      {children}
      <IconButton size="small" aria-label={t("builder.remove", { name: label })} onClick={onRemove} sx={{ p: 0.25 }}>
        <CloseIcon sx={{ fontSize: 16 }} />
      </IconButton>
    </Box>
  );
}
