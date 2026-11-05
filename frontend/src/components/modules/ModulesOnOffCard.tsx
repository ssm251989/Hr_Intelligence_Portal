import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { modulesApi } from "../../api/setupApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";

// Part 18.5: switch any allowed module on or off (People, Performance, Helpdesk are off by
// default). Saving updates the menu straight away.
export default function ModulesOnOffCard() {
  const t = useT();
  const { reload } = useMeBootstrap();
  const [items, setItems] = useState<{ code: string; on: boolean; offered: boolean }[] | null>(null);
  const [on, setOn] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    modulesApi.list().then((list) => {
      setItems(list);
      setOn(new Set(list.filter((m) => m.on).map((m) => m.code)));
    }).catch((err) => setMsg({ ok: false, text: extractErrorMessage(err, t("modules.err")) }));
  }, [t]);

  const dirty = items !== null && items.some((m) => m.on !== on.has(m.code));
  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await modulesApi.save(Array.from(on));
      const list = await modulesApi.list();
      setItems(list);
      reload();
      setMsg({ ok: true, text: t("modules.saved") });
    } catch (err) {
      setMsg({ ok: false, text: extractErrorMessage(err, t("modules.err")) });
    } finally {
      setBusy(false);
    }
  };

  if (!items) return msg ? <Alert severity="error">{msg.text}</Alert> : null;
  return (
    <Card>
      <CardContent>
        <Typography variant="h6">{t("modules.title")}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{t("modules.intro")}</Typography>
        <Stack>
          {items.map((m) => (
            <FormControlLabel key={m.code} label={t(`setup.module.${m.code}`)}
              control={<Switch checked={on.has(m.code)} onChange={(e) => setOn((prev) => {
                const next = new Set(prev);
                if (e.target.checked) next.add(m.code); else next.delete(m.code);
                return next;
              })} />} />
          ))}
        </Stack>
        {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mt: 1 }}>{msg.text}</Alert>}
        <Button variant="contained" sx={{ mt: 1.5 }} disabled={!dirty || busy} onClick={save}>{t("lock.save")}</Button>
      </CardContent>
    </Card>
  );
}
