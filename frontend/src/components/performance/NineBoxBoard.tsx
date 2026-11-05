import { useState } from "react";
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import DriveFileMoveOutlinedIcon from "@mui/icons-material/DriveFileMoveOutlined";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import ListSubheader from "@mui/material/ListSubheader";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { NineBox, TeamMember } from "../../api/performanceExtra";
import { useT } from "../../i18n";
import { Emoji, InfoTip, UserAvatar, useReducedMotion } from "../../ui-kit";
import { useFresh } from "./shared";

// F5: the 9-box -- performance (left to right) x potential (bottom to top). Drag a card to
// a box, or use the card's "Move to box" menu (keyboard / screen reader path). Both call
// `onPlace(person, box)`; the page saves it.

export const UNPLACED = "unplaced";
const boxId = (b: NineBox) => `${b.performance}x${b.potential}`;
const EMOJI: Record<string, string> = {
  "3x3": "rocket", "2x3": "seedling", "1x3": "thinking",
  "3x2": "star", "2x2": "thumbs_up", "1x2": "confused",
  "3x1": "trophy", "2x1": "check", "1x1": "warning",
};

function MoveMenu({ person, onPlace }: { person: TeamMember; onPlace: (p: TeamMember, b: NineBox | null) => void }) {
  const t = useT();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const current = person.nine_box ? boxId(person.nine_box) : UNPLACED;
  return (
    <>
      <Tooltip title={t("performance.ninebox.move")}>
        <IconButton
          size="small"
          aria-label={t("performance.ninebox.move_named", { name: person.name })}
          aria-haspopup="menu"
          onClick={(e) => setAnchor(e.currentTarget)}
          onPointerDown={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <DriveFileMoveOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {[3, 2, 1].map((pot) => [
          <ListSubheader key={`h${pot}`}>{t(`performance.ninebox.potential_${pot}`)}</ListSubheader>,
          ...[3, 2, 1].map((perf) => {
            const id = `${perf}x${pot}`;
            return (
              <MenuItem key={id} disabled={id === current} onClick={() => { setAnchor(null); onPlace(person, { performance: perf, potential: pot }); }}>
                <Emoji name={EMOJI[id]} size={16} />
                <Box component="span" sx={{ ml: 1 }}>{t(`performance.ninebox.box.${id}`)} · {t(`performance.ninebox.perf_${perf}`)}</Box>
              </MenuItem>
            );
          }),
        ])}
        {current !== UNPLACED && (
          <MenuItem onClick={() => { setAnchor(null); onPlace(person, null); }}>
            <Emoji name="cross" size={16} />
            <Box component="span" sx={{ ml: 1 }}>{t("performance.ninebox.unplace")}</Box>
          </MenuItem>
        )}
      </Menu>
    </>
  );
}

function PersonCard({ person, canEdit, onPlace, saving }: { person: TeamMember; canEdit: boolean; onPlace: (p: TeamMember, b: NineBox | null) => void; saving: boolean }) {
  const f = useFresh();
  const t = useT();
  const reduced = useReducedMotion();
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: person.employee_id, disabled: !canEdit || saving });
  return (
    <Box
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      aria-label={t("performance.ninebox.card_label", { name: person.name })}
      sx={{
        display: "flex", alignItems: "center", gap: 1, p: 0.75, pr: 0.25, borderRadius: "12px", bgcolor: f.surface, border: `1px solid ${f.line}`,
        cursor: canEdit ? "grab" : "default", touchAction: "none", position: "relative", zIndex: isDragging ? 20 : undefined, opacity: saving ? 0.6 : 1,
        boxShadow: isDragging ? f.shadowHover : "none", transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
        transition: reduced || isDragging ? undefined : "box-shadow 150ms ease",
        "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 },
      }}
    >
      <UserAvatar name={person.name} size={28} />
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography sx={{ fontSize: 13, fontWeight: 700 }} noWrap>{person.name}</Typography>
        {person.designation && <Typography sx={{ fontSize: 11, color: f.muted }} noWrap>{person.designation}</Typography>}
      </Box>
      {canEdit && <MoveMenu person={person} onPlace={onPlace} />}
    </Box>
  );
}

function Cell({ id, title, emoji, people, ...rest }: { id: string; title: string; emoji: string; people: TeamMember[]; canEdit: boolean; onPlace: (p: TeamMember, b: NineBox | null) => void; savingId: string | null; tone: string }) {
  const f = useFresh();
  const t = useT();
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <Box
      ref={setNodeRef}
      role="region"
      aria-label={t("performance.ninebox.cell_label", { title, count: people.length })}
      sx={{
        minHeight: 140, p: 1.25, borderRadius: "14px", bgcolor: isOver ? f.brandSoft : rest.tone, border: `2px dashed ${isOver ? f.brand : "transparent"}`,
        display: "flex", flexDirection: "column", gap: 0.75,
      }}
    >
      <Stack direction="row" spacing={0.75} alignItems="center">
        <Emoji name={emoji} size={16} />
        <Typography sx={{ fontWeight: 800, fontSize: 13, flex: 1 }}>{title}</Typography>
        <Typography sx={{ fontSize: 12, color: f.muted, fontWeight: 700 }}>{t("performance.ninebox.count", { count: people.length })}</Typography>
      </Stack>
      {people.map((p) => <PersonCard key={p.employee_id} person={p} canEdit={rest.canEdit} onPlace={rest.onPlace} saving={rest.savingId === p.employee_id} />)}
    </Box>
  );
}

export default function NineBoxBoard({ people, canEdit, onPlace, savingId }: { people: TeamMember[]; canEdit: boolean; onPlace: (p: TeamMember, b: NineBox | null) => void; savingId: string | null }) {
  const t = useT();
  const f = useFresh();
  // Keyboard dragging is off on purpose (arrow-by-pixels is not friendly); the menu is the keyboard path.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const byBox: Record<string, TeamMember[]> = {};
  for (const p of people) {
    const key = p.nine_box ? boxId(p.nine_box) : UNPLACED;
    (byBox[key] ??= []).push(p);
  }
  const onDragEnd = (e: DragEndEvent) => {
    const person = people.find((p) => p.employee_id === e.active.id);
    const over = e.over?.id ? String(e.over.id) : null;
    if (!person || !over) return;
    const current = person.nine_box ? boxId(person.nine_box) : UNPLACED;
    if (over === current) return;
    if (over === UNPLACED) return onPlace(person, null);
    const [perf, pot] = over.split("x").map(Number);
    onPlace(person, { performance: perf, potential: pot });
  };
  const tone = (perf: number, pot: number) => (perf + pot >= 5 ? f.okSoft : perf + pot <= 3 ? f.coralSoft : f.surface2);

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "32px repeat(3, minmax(0, 1fr))" }, gap: 1.25 }}>
        {[3, 2, 1].map((pot) => [
          <Box key={`y${pot}`} sx={{ display: { xs: "none", md: "flex" }, alignItems: "center", justifyContent: "center" }}>
            <Typography sx={{ writingMode: "vertical-rl", transform: "rotate(180deg)", fontSize: 12, fontWeight: 700, color: f.muted }}>{t(`performance.ninebox.potential_${pot}`)}</Typography>
          </Box>,
          ...[1, 2, 3].map((perf) => {
            const id = `${perf}x${pot}`;
            return <Cell key={id} id={id} title={t(`performance.ninebox.box.${id}`)} emoji={EMOJI[id]} people={byBox[id] ?? []} canEdit={canEdit} onPlace={onPlace} savingId={savingId} tone={tone(perf, pot)} />;
          }),
        ])}
        <Box sx={{ display: { xs: "none", md: "block" } }} />
        {[1, 2, 3].map((perf) => (
          <Typography key={`x${perf}`} sx={{ display: { xs: "none", md: "block" }, textAlign: "center", fontSize: 12, fontWeight: 700, color: f.muted }}>{t(`performance.ninebox.perf_${perf}`)}</Typography>
        ))}
      </Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.5, mb: 1 }}>
        <Typography sx={{ fontWeight: 800 }}>{t("performance.ninebox.axis")}</Typography>
        <InfoTip text={t("performance.ninebox.axis_tip")} />
      </Stack>
      <Cell id={UNPLACED} title={t("performance.ninebox.unplaced")} emoji="hourglass" people={byBox[UNPLACED] ?? []} canEdit={canEdit} onPlace={onPlace} savingId={savingId} tone={f.surface2} />
    </DndContext>
  );
}
