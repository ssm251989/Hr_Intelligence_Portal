import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { serviceDeskExtra, type Category } from "../../api/serviceDeskExtra";
import { useI18n } from "../../i18n";

// Part 20.0-D: Settings > Helpdesk & assets > Asset categories / Exit reasons. Add, rename, switch
// off (never delete - assets and exits keep pointing at the item). Works with the Assets / Exits
// modules hidden.

type Kind = "asset" | "exit_reason" | "ticket";

export default function CategoryListPage({ kind }: { kind: Kind }) {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const [rows, setRows] = useState<Category[] | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [label, setLabel] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => serviceDeskExtra.allCategories(kind, locale).then((r) => {
    setRows(r);
    setNames(Object.fromEntries(r.map((c) => [c.code, c.label])));
  }).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, "") })), [kind, locale]);
  useEffect(() => { load(); }, [load]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    }
  };

  return (
    <Card>
      <CardContent>
        <Typography color="text.secondary" sx={{ mb: 2 }}>{t(`catlist.${kind}.intro`)}</Typography>
        {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)} sx={{ mb: 2 }}>{msg.text}</Alert>}
        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          <TextField size="small" fullWidth label={t(`catlist.${kind}.new`)} value={label} onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && label.trim()) void run(() => serviceDeskExtra.addCategory(kind, label.trim(), locale).then(() => setLabel("")), t("catlist.added")); }} />
          <Button variant="contained" disabled={!label.trim()}
            onClick={() => run(() => serviceDeskExtra.addCategory(kind, label.trim(), locale).then(() => setLabel("")), t("catlist.added"))}>{t("catlist.add")}</Button>
        </Stack>
        {rows === null ? <Skeleton variant="rounded" height={200} /> : (
          <Stack spacing={1} data-testid={`catlist-${kind}`}>
            {rows.map((c) => (
              <Stack key={c.code} direction="row" spacing={1} alignItems="center" sx={{ p: 1, border: `1px solid ${f.line}`, borderRadius: "10px", opacity: c.active === false ? 0.6 : 1 }}>
                <TextField size="small" sx={{ flex: 1 }} value={names[c.code] ?? ""} onChange={(e) => setNames((n) => ({ ...n, [c.code]: e.target.value }))}
                  inputProps={{ "aria-label": c.label }} />
                {(names[c.code] ?? "").trim() && names[c.code] !== c.label && (
                  <Button size="small" onClick={() => run(() => serviceDeskExtra.editCategory(kind, c.code, { label: names[c.code].trim() }, locale), t("catlist.saved"))}>{t("catlist.save")}</Button>
                )}
                <Box sx={{ minWidth: 130 }}>
                  <FormControlLabel control={<Switch size="small" checked={c.active !== false}
                    onChange={(e) => run(() => serviceDeskExtra.editCategory(kind, c.code, { active: e.target.checked }, locale), t("catlist.saved"))} />}
                    label={c.active === false ? t("catlist.off") : t("catlist.on")} />
                </Box>
              </Stack>
            ))}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
