import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, http } from "../../api/client";
import { useT } from "../../i18n";
import ConfirmDialog from "../ConfirmDialog";
import PlacesMap from "../maps/PlacesMap";

interface Loc { id: string; name: string; address: string | null; state: string | null; timezone: string | null; geo_lat: string | null; geo_lng: string | null }
type Draft = { name: string; address: string; state: string; geo_lat: string; geo_lng: string };
const blank: Draft = { name: "", address: "", state: "", geo_lat: "", geo_lng: "" };

// Part 18.22: Settings > Company > Offices & locations -- add, edit, delete, and the map position
// (type latitude / longitude, or use "Fix position" on the map below).
export default function OfficesPage() {
  const t = useT();
  const [rows, setRows] = useState<Loc[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [adding, setAdding] = useState<Draft>(blank);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [removing, setRemoving] = useState<Loc | null>(null);
  const [mapKey, setMapKey] = useState(0);

  const load = useCallback(() => {
    http.get<{ locations: Loc[] }>("/api/v1/ui/locations").then((r) => {
      setRows(r.locations);
      setDrafts(Object.fromEntries(r.locations.map((l) => [l.id, { name: l.name, address: l.address ?? "", state: l.state ?? "", geo_lat: l.geo_lat ?? "", geo_lng: l.geo_lng ?? "" }])));
      setMapKey((k) => k + 1);
    }).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, t("offices.err")) }));
  }, [t]);
  useEffect(load, [load]);

  const body = (d: Draft) => ({ name: d.name, address: d.address || null, state: d.state || null,
    geo_lat: d.geo_lat === "" ? null : Number(d.geo_lat), geo_lng: d.geo_lng === "" ? null : Number(d.geo_lng) });
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); } catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("offices.err")) }); }
  };
  const fields = (d: Draft, set: (d: Draft) => void) => (
    <>
      <TextField size="small" label={t("offices.name")} value={d.name} onChange={(e) => set({ ...d, name: e.target.value })} placeholder={t("offices.eg_name")} sx={{ minWidth: 180 }} />
      <TextField size="small" label={t("offices.address")} value={d.address} onChange={(e) => set({ ...d, address: e.target.value })} sx={{ minWidth: 200 }} />
      <TextField size="small" label={t("offices.state")} value={d.state} onChange={(e) => set({ ...d, state: e.target.value })} sx={{ width: 140 }} />
      <TextField size="small" type="number" label={t("offices.lat")} value={d.geo_lat} onChange={(e) => set({ ...d, geo_lat: e.target.value })} placeholder="13.0827" sx={{ width: 120 }} />
      <TextField size="small" type="number" label={t("offices.lng")} value={d.geo_lng} onChange={(e) => set({ ...d, geo_lng: e.target.value })} placeholder="80.2707" sx={{ width: 120 }} />
    </>
  );

  return (
    <Stack spacing={2}>
      <Card>
        <CardContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{t("offices.intro")}</Typography>
          {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
          <Stack spacing={1.25}>
            {(rows ?? []).map((l) => (
              <Stack key={l.id} direction={{ xs: "column", lg: "row" }} spacing={1} alignItems={{ lg: "center" }}>
                {fields(drafts[l.id] ?? blank, (d) => setDrafts((x) => ({ ...x, [l.id]: d })))}
                <Button size="small" variant="contained" disabled={!drafts[l.id]?.name}
                  onClick={() => run(() => http.patch(`/api/v1/ui/locations/${l.id}`, body(drafts[l.id])), t("offices.saved"))}>{t("lock.save")}</Button>
                <Button size="small" color="error" onClick={() => setRemoving(l)}>{t("offices.delete")}</Button>
              </Stack>
            ))}
          </Stack>
          <Typography sx={{ fontWeight: 700, mt: 3, mb: 1 }}>{t("offices.add")}</Typography>
          <Stack direction={{ xs: "column", lg: "row" }} spacing={1} alignItems={{ lg: "center" }}>
            {fields(adding, setAdding)}
            <Button variant="contained" disabled={!adding.name} onClick={() => run(() => http.post("/api/v1/ui/locations", body(adding)).then(() => setAdding(blank)), t("offices.added"))}>{t("offices.add_btn")}</Button>
          </Stack>
        </CardContent>
      </Card>
      <PlacesMap key={mapKey} kind="offices" />
      <ConfirmDialog open={removing !== null} title={t("offices.delete_title", { name: removing?.name ?? "" })} message={t("offices.delete_body")}
        confirmLabel={t("offices.delete")} destructive
        onConfirm={() => { const l = removing; setRemoving(null); if (l) void run(() => http.del(`/api/v1/ui/locations/${l.id}`), t("offices.deleted")); }}
        onCancel={() => setRemoving(null)} />
    </Stack>
  );
}
