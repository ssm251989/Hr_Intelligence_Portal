import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import InputBase from "@mui/material/InputBase";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { CompRow } from "../../api/performanceExtra";
import { useT } from "../../i18n";
import { Emoji, InfoTip, StatusChip, UserAvatar } from "../../ui-kit";
import { PerfChip, isMasked, useFresh } from "./shared";

// F7: spreadsheet-style pay review grid. Increase %, increase amount and bonus are typed
// straight into the cell: Enter saves and moves down, Esc undoes, arrow up/down moves
// between rows, Tab moves across. Values hidden by field security show a lock instead.

type Col = "pct" | "amount" | "bonus";
const COLS: Col[] = ["pct", "amount", "bonus"];

function EditCell({
  row, col, rowIndex, value, disabled, onCommit, ariaLabel, suffix,
}: {
  row: CompRow; col: Col; rowIndex: number; value: number | null; disabled: boolean; onCommit: (row: CompRow, col: Col, v: number) => void; ariaLabel: string; suffix?: string;
}) {
  const f = useFresh();
  const [text, setText] = useState(value == null ? "" : String(round(value)));
  const orig = useRef(text);
  useEffect(() => {
    const next = value == null ? "" : String(round(value));
    setText(next);
    orig.current = next;
  }, [value]);

  const commit = () => {
    if (text === orig.current) return;
    const n = Number(text);
    if (text.trim() === "" || Number.isNaN(n) || n < 0) {
      setText(orig.current);
      return;
    }
    orig.current = text;
    onCommit(row, col, n);
  };
  const move = (dRow: number) => {
    const el = document.querySelector<HTMLInputElement>(`[data-comp-cell="${rowIndex + dRow}-${col}"]`);
    el?.focus();
    el?.select();
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
      move(1);
    } else if (e.key === "Escape") {
      setText(orig.current);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      commit();
      move(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      commit();
      move(-1);
    }
  };
  return (
    <InputBase
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={onKey}
      onFocus={(e) => e.target.select()}
      disabled={disabled}
      inputProps={{ "aria-label": ariaLabel, inputMode: "decimal", "data-comp-cell": `${rowIndex}-${col}` }}
      endAdornment={suffix ? <Typography sx={{ fontSize: 12, color: f.muted, ml: 0.25 }}>{suffix}</Typography> : undefined}
      sx={{
        width: col === "pct" ? 84 : 128, px: 1, py: 0.25, borderRadius: "8px", fontVariantNumeric: "tabular-nums", fontSize: 14,
        border: `1px solid ${disabled ? "transparent" : f.line}`, bgcolor: disabled ? "transparent" : f.surface,
        "&.Mui-focused": { borderColor: f.brand, boxShadow: `0 0 0 2px ${f.brandSoft}` },
      }}
    />
  );
}

const round = (n: number) => Math.round(n * 100) / 100;

function BandCell({ row, money }: { row: CompRow; money: (v: number | string | null) => string }) {
  const f = useFresh();
  const t = useT();
  if (!row.band) return <Typography sx={{ color: f.muted, fontSize: 13 }}>{row.grade ?? "—"}</Typography>;
  const base = typeof row.current_base === "number" ? row.current_base : null;
  const { min, max } = row.band;
  const pos = base == null || max === min ? null : Math.max(0, Math.min(100, ((base - min) / (max - min)) * 100));
  return (
    <Tooltip title={t("compensation.grid.band_range", { min: money(min), mid: money(row.band.mid), max: money(max) })}>
      <Box sx={{ minWidth: 110 }} aria-label={t("compensation.grid.band_range", { min: money(min), mid: money(row.band.mid), max: money(max) })}>
        <Typography sx={{ fontSize: 12, fontWeight: 700 }}>{row.grade}</Typography>
        <Box sx={{ position: "relative", height: 6, borderRadius: 999, bgcolor: f.brandSoft, mt: 0.5 }}>
          {pos != null && <Box sx={{ position: "absolute", left: `calc(${pos}% - 5px)`, top: -2, width: 10, height: 10, borderRadius: "50%", bgcolor: f.brand, border: `2px solid ${f.surface}` }} />}
        </Box>
      </Box>
    </Tooltip>
  );
}

export default function CompGrid({
  rows, money, canEdit, canSeeBands, onChange, onSubmit, busyId,
}: {
  rows: CompRow[];
  money: (v: number | string | null | undefined) => string;
  canEdit: boolean;
  canSeeBands: boolean;
  onChange: (row: CompRow, patch: { merit_pct?: number; bonus_amount?: number }) => void;
  onSubmit: (row: CompRow) => void;
  busyId: string | null;
}) {
  const t = useT();
  const f = useFresh();

  const commit = (row: CompRow, col: Col, v: number) => {
    if (col === "pct") onChange(row, { merit_pct: v });
    else if (col === "bonus") onChange(row, { bonus_amount: v });
    else if (typeof row.current_base === "number" && row.current_base > 0) onChange(row, { merit_pct: round((v / row.current_base) * 100) });
  };

  return (
    <TableContainer sx={{ maxHeight: "70vh" }}>
      <Table size="small" stickyHeader aria-label={t("compensation.grid.label")}>
        <TableHead>
          <TableRow>
            <TableCell>{t("compensation.grid.person")}</TableCell>
            <TableCell>{t("compensation.grid.band")}<InfoTip text={t("compensation.grid.band_tip")} /></TableCell>
            <TableCell align="right">{t("compensation.grid.current")}</TableCell>
            <TableCell align="right">{t("compensation.grid.compa")}<InfoTip text={t("compensation.grid.compa_tip")} /></TableCell>
            <TableCell align="right">{t("compensation.grid.rating")}</TableCell>
            <TableCell>{t("compensation.grid.guideline")}<InfoTip text={t("compensation.grid.guideline_tip")} /></TableCell>
            <TableCell>{t("compensation.grid.pct")}</TableCell>
            <TableCell>{t("compensation.grid.amount")}</TableCell>
            <TableCell align="right">{t("compensation.grid.new")}</TableCell>
            <TableCell>{t("compensation.grid.bonus")}</TableCell>
            <TableCell>{t("compensation.grid.status")}</TableCell>
            <TableCell align="right">{t("compensation.grid.action")}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r, i) => {
            const baseHidden = isMasked(r.current_base);
            const base = typeof r.current_base === "number" ? r.current_base : null;
            const pct = r.merit_pct ?? 0;
            const amount = base != null ? (base * pct) / 100 : null;
            const editable = canEdit && r.status === "draft";
            const compa = typeof r.compa_ratio === "number" ? r.compa_ratio : null;
            const [gMin, gMax] = r.guideline;
            return (
              <TableRow key={r.id} hover sx={{ bgcolor: r.outside_guideline ? f.sunSoft : undefined }}>
                <TableCell>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <UserAvatar name={r.name} size={30} />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>{r.name}</Typography>
                      <Typography sx={{ fontSize: 12, color: f.muted }} noWrap>{[r.designation, r.department].filter(Boolean).join(" · ") || "—"}</Typography>
                    </Box>
                  </Stack>
                </TableCell>
                <TableCell>{canSeeBands ? <BandCell row={r} money={money} /> : <Typography sx={{ fontSize: 13 }}>{r.grade ?? "—"}</Typography>}</TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>
                  {baseHidden ? <StatusChip tone="muted" emoji="lock" label={t("compensation.grid.hidden")} /> : money(base)}
                </TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>
                  {isMasked(r.compa_ratio) ? <Emoji name="lock" size={14} /> : compa != null ? (
                    <Tooltip title={t(compa < 0.9 ? "compensation.grid.compa_low" : compa > 1.1 ? "compensation.grid.compa_high" : "compensation.grid.compa_mid")}>
                      <span>{compa.toFixed(2)}</span>
                    </Tooltip>
                  ) : "—"}
                </TableCell>
                <TableCell align="right">{r.rating != null ? r.rating : "—"}</TableCell>
                <TableCell sx={{ whiteSpace: "nowrap", fontSize: 13 }}>{gMin != null && gMax != null ? t("compensation.grid.guideline_range", { min: gMin, max: gMax }) : "—"}</TableCell>
                <TableCell>
                  <EditCell row={r} col="pct" rowIndex={i} value={r.merit_pct} disabled={!editable} onCommit={commit} suffix="%" ariaLabel={t("compensation.grid.pct_for", { name: r.name })} />
                </TableCell>
                <TableCell>
                  <EditCell row={r} col="amount" rowIndex={i} value={amount} disabled={!editable || base == null} onCommit={commit} ariaLabel={t("compensation.grid.amount_for", { name: r.name })} />
                </TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>{base != null ? money(base + (amount ?? 0)) : "—"}</TableCell>
                <TableCell>
                  {isMasked(r.bonus_amount) ? <Emoji name="lock" size={14} /> : (
                    <EditCell row={r} col="bonus" rowIndex={i} value={typeof r.bonus_amount === "number" ? r.bonus_amount : null} disabled={!editable} onCommit={commit} ariaLabel={t("compensation.grid.bonus_for", { name: r.name })} />
                  )}
                </TableCell>
                <TableCell>
                  <Stack spacing={0.5} alignItems="flex-start">
                    <PerfChip status={r.status} />
                    {r.outside_guideline && <StatusChip tone="sun" emoji="warning" label={t("compensation.grid.outside")} />}
                  </Stack>
                </TableCell>
                <TableCell align="right">
                  {editable && (
                    <Button size="small" variant="outlined" onClick={() => onSubmit(r)} disabled={busyId === r.id}>
                      {t("compensation.grid.submit")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

export { COLS };
