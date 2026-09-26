import { useState, type ReactNode } from "react";
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import DriveFileMoveOutlinedIcon from "@mui/icons-material/DriveFileMoveOutlined";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { CandidateApplicationRow } from "../../api/types";
import { useT } from "../../i18n";
import { Emoji, StatusChip, useReducedMotion } from "../../ui-kit";
import { resumeMatchScoreDisplay } from "../../utils/screeningScore";
import CandidateAvatar from "../CandidateAvatar";
import SourceIcon from "../SourceIcon";
import { BOARD_COLUMNS, columnOf, useFresh, type BoardColumnKey } from "./stages";

// Part 15.4 C4: the Kanban half of the Candidates list. Drag a card to another stage
// (@dnd-kit/core) or -- for keyboard and screen-reader users -- use the card's
// "Move to stage" menu; both hand the same (row, column) to `onMove`, which decides
// whether the move is allowed and calls the existing endpoint.

interface Props {
  rows: CandidateApplicationRow[];
  canWrite: boolean;
  onMove: (row: CandidateApplicationRow, to: BoardColumnKey) => void;
  onOpen: (row: CandidateApplicationRow) => void;
  renderActions?: (row: CandidateApplicationRow) => ReactNode;
}

function MoveMenu({ row, onMove }: { row: CandidateApplicationRow; onMove: Props["onMove"] }) {
  const t = useT();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const current = columnOf(row.status);
  return (
    <>
      <Tooltip title={t("candidates.kanban.move_to")}>
        <IconButton
          size="small"
          aria-label={t("candidates.kanban.move_named", { name: row.candidate_name || t("candidates.unnamed") })}
          aria-haspopup="menu"
          onClick={(e) => {
            e.stopPropagation();
            setAnchor(e.currentTarget);
          }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <DriveFileMoveOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)} onClick={(e) => e.stopPropagation()}>
        {BOARD_COLUMNS.filter((c) => c.key !== current).map((c) => (
          <MenuItem
            key={c.key}
            onClick={() => {
              setAnchor(null);
              onMove(row, c.key);
            }}
          >
            <Emoji name={c.emoji} size={16} />
            <Box component="span" sx={{ ml: 1 }}>{t(`candidates.stage.${c.key}`)}</Box>
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

function KanbanCard({ row, canWrite, onMove, onOpen, renderActions }: { row: CandidateApplicationRow } & Omit<Props, "rows">) {
  const t = useT();
  const f = useFresh();
  const reduced = useReducedMotion();
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: row.application_id, disabled: !canWrite });
  const { value: score } = resumeMatchScoreDisplay(row);
  const name = row.candidate_name || t("candidates.unnamed");
  // dnd-kit's own keyboard handling is not used (arrow-moving a card by pixels is not a
  // friendly keyboard model); the "Move to stage" menu is the keyboard path instead.
  const { role: _role, tabIndex: _tabIndex, ...dragAttributes } = attributes;
  void _role;
  void _tabIndex;

  return (
    <Box
      ref={setNodeRef}
      {...dragAttributes}
      {...listeners}
      data-testid={`kanban-card-${row.application_id}`}
      sx={{
        bgcolor: f.surface, border: `1px solid ${f.line}`, borderRadius: "14px", p: 1.25, boxShadow: isDragging ? f.shadowHover : "none",
        cursor: canWrite ? "grab" : "default", touchAction: "none", position: "relative", zIndex: isDragging ? 10 : undefined,
        transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
        transition: reduced || isDragging ? undefined : "box-shadow 150ms ease",
        opacity: isDragging ? 0.92 : 1,
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center">
        <CandidateAvatar candidateId={row.candidate_id} photoPath={row.photo_path} name={row.candidate_name} email={row.candidate_email} sx={{ width: 32, height: 32, fontSize: 12 }} />
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography
            component="button"
            type="button"
            onClick={() => onOpen(row)}
            onPointerDown={(e) => e.stopPropagation()}
            sx={{ all: "unset", cursor: "pointer", fontWeight: 700, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%", "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2, borderRadius: 1 } }}
          >
            {name}
          </Typography>
          <Typography sx={{ fontSize: 12, color: f.muted }} noWrap>{row.job_title}</Typography>
        </Box>
      </Stack>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 1, flexWrap: "wrap", rowGap: 0.5 }}>
        <StatusChip status={row.status} />
        {score != null && <StatusChip tone="brand" emoji="star" label={t("candidates.score_short", { score: Math.round(score) })} />}
        <Box sx={{ flex: 1 }} />
        <SourceIcon source={row.source} />
        {canWrite && <MoveMenu row={row} onMove={onMove} />}
        <Box onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>{renderActions?.(row)}</Box>
      </Stack>
    </Box>
  );
}

function KanbanColumn({ columnKey, emoji, rows, ...rest }: { columnKey: BoardColumnKey; emoji: string; rows: CandidateApplicationRow[] } & Omit<Props, "rows">) {
  const t = useT();
  const f = useFresh();
  const { setNodeRef, isOver } = useDroppable({ id: columnKey });
  return (
    <Box
      ref={setNodeRef}
      role="region"
      aria-label={t("candidates.kanban.column_label", { stage: t(`candidates.stage.${columnKey}`), count: rows.length })}
      sx={{
        flex: "0 0 272px", width: 272, bgcolor: isOver ? f.brandSoft : f.surface2, borderRadius: "18px", p: 1.25,
        border: `2px dashed ${isOver ? f.brand : "transparent"}`, display: "flex", flexDirection: "column", gap: 1, maxHeight: "70vh",
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center" sx={{ px: 0.5, pt: 0.25 }}>
        <Emoji name={emoji} size={18} />
        <Typography sx={{ fontWeight: 700, flex: 1 }}>{t(`candidates.stage.${columnKey}`)}</Typography>
        <Typography sx={{ fontSize: 12, fontWeight: 700, color: f.muted, fontVariantNumeric: "tabular-nums" }}>
          {t("count.candidates", { count: rows.length })}
        </Typography>
      </Stack>
      <Stack spacing={1} sx={{ overflowY: "auto", minHeight: 60, pb: 0.5 }}>
        {rows.length === 0 ? (
          <Typography sx={{ fontSize: 12, color: f.muted, textAlign: "center", py: 2 }}>{t("candidates.kanban.empty_column")}</Typography>
        ) : (
          rows.map((row) => <KanbanCard key={row.application_id} row={row} {...rest} />)
        )}
      </Stack>
    </Box>
  );
}

export default function CandidatesKanban({ rows, ...rest }: Props) {
  const { onMove } = rest;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const byColumn = new Map<BoardColumnKey, CandidateApplicationRow[]>(BOARD_COLUMNS.map((c) => [c.key, []]));
  rows.forEach((row) => byColumn.get(columnOf(row.status))!.push(row));

  const handleDragEnd = (event: DragEndEvent) => {
    const to = event.over?.id as BoardColumnKey | undefined;
    const row = rows.find((r) => r.application_id === event.active.id);
    if (!to || !row || columnOf(row.status) === to) return; // dropped nowhere / same column: card snaps back
    onMove(row, to);
  };

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <Box sx={{ display: "flex", gap: 1.5, overflowX: "auto", pb: 1.5 }} data-testid="candidates-kanban">
        {BOARD_COLUMNS.map((c) => (
          <KanbanColumn key={c.key} columnKey={c.key} emoji={c.emoji} rows={byColumn.get(c.key)!} {...rest} />
        ))}
      </Box>
    </DndContext>
  );
}
