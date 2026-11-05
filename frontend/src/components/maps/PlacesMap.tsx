// Part 17.3: the one map used everywhere (Home "People by office", Jobs and Analytics "Jobs
// by location"). Real Leaflet map, tiles from the company's `geo.tile_url` setting
// (OpenStreetMap by default), zoom/pan, marker clusters that add up their places, and
// auto-fit to the markers inside the allowed-country box. Bubble size = count; the popup
// shows the place, the count and a button that opens the matching list. Places that can't
// be put on the map are listed under it ("Location not found - fix it") with a Fix button.
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import L, { latLngBounds } from "leaflet";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate } from "react-router-dom";

import { geoApi, type GeoConfig, type MapPlace, type PlaceKind, type PlacesResult, type UnplacedPlace } from "../../api/geoApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError } from "../../ui-kit";

const FALLBACK_CENTER: [number, number] = [22.5, 80];
const FIX_PERMISSION: Record<PlaceKind, string> = { offices: "core_hr.org.edit", jobs: "recruitment.job.edit" };

let clusterReady: Promise<void> | null = null;
function loadCluster(): Promise<void> {
  clusterReady ??= (async () => {
    (window as unknown as { L: typeof L }).L = L;
    await import("leaflet.markercluster");
  })();
  return clusterReady;
}

function useCluster(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    loadCluster().then(() => alive && setReady(true)).catch(() => alive && setReady(false));
    return () => { alive = false; };
  }, []);
  return ready;
}

let configCache: Promise<GeoConfig> | null = null;
const loadConfig = () => (configCache ??= geoApi.config().catch((e) => { configCache = null; throw e; }));

function AutoFit({ points }: { points: [number, number][] }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join("|");
  useEffect(() => {
    const fit = () => {
      map.invalidateSize();
      if (points.length === 1) map.setView(points[0], 10);
      else if (points.length > 1) map.fitBounds(latLngBounds(points), { padding: [36, 36], maxZoom: 10 });
    };
    const raf = requestAnimationFrame(fit);
    // the map lives in resizable home boxes -- re-measure whenever its box changes size
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    return () => { cancelAnimationFrame(raf); observer.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

function Markers({ places, colour, ink, countLabel, openLabel, onOpen }: {
  places: MapPlace[]; colour: string; ink: string; countLabel: (n: number) => string; openLabel: string; onOpen: (p: MapPlace) => void;
}) {
  const map = useMap();
  useEffect(() => {
    const max = Math.max(1, ...places.map((p) => p.count));
    const bubble = (n: number, size: number) => L.divIcon({
      html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${colour};color:${ink};display:grid;place-items:center;font-weight:800;font-size:${size > 34 ? 14 : 12}px;box-shadow:0 0 0 4px ${colour}44">${n}</div>`,
      className: "", iconSize: [size, size],
    });
    const group = L.markerClusterGroup({
      showCoverageOnHover: false, maxClusterRadius: 45,
      iconCreateFunction: (cluster) => {
        const sum = cluster.getAllChildMarkers().reduce((acc, m) => acc + ((m.options as { count?: number }).count ?? 0), 0);
        return bubble(sum, 44);
      },
    });
    for (const p of places) {
      const size = Math.round(26 + (p.count / max) * 22);
      const marker = L.marker([p.lat, p.lng], { icon: bubble(p.count, size), count: p.count, keyboard: true, title: `${p.label ?? ""}: ${countLabel(p.count)}` } as L.MarkerOptions & { count: number });
      const box = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = p.label ?? "";
      const line = document.createElement("div");
      line.textContent = countLabel(p.count);
      line.style.margin = "2px 0 8px";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = openLabel;
      button.style.cssText = `border:0;border-radius:8px;padding:6px 10px;background:${colour};color:${ink};font:inherit;font-weight:700;cursor:pointer`;
      button.onclick = () => onOpen(p);
      box.append(title, line, button);
      marker.bindPopup(box);
      marker.bindTooltip(`${p.label ?? ""}: ${countLabel(p.count)}`);
      group.addLayer(marker);
    }
    map.addLayer(group);
    return () => { map.removeLayer(group); };
  }, [map, places, colour, ink, countLabel, openLabel, onOpen]);
  return null;
}

function FixDialog({ item, onClose, onFixed }: { item: UnplacedPlace | null; onClose: () => void; onFixed: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [city, setCity] = useState("");
  const [point, setPoint] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { if (item) { setCity(""); setPoint(""); setError(null); } }, [item]);
  const parsed = point.split(",").map((x) => Number(x.trim()));
  const pointOk = parsed.length === 2 && parsed.every((x) => Number.isFinite(x));
  const save = async () => {
    if (!item) return;
    setSaving(true);
    setError(null);
    try {
      await geoApi.fix({ ...item.fix, ...(pointOk ? { lat: parsed[0], lng: parsed[1], city: city.trim() || undefined } : { city: city.trim() }) });
      onFixed();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={Boolean(item)} onClose={saving ? undefined : onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t("maps.fix.title", { place: item?.label || t("maps.no_place") })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography sx={{ fontSize: 14, color: f.muted }}>{t("maps.fix.intro")}</Typography>
          <TextField autoFocus label={t("maps.fix.city")} placeholder={t("maps.fix.city_ph")} value={city} onChange={(e) => setCity(e.target.value)} />
          <TextField label={t("maps.fix.point")} placeholder="17.3850, 78.4867" helperText={t("maps.fix.point_hint")} value={point}
            onChange={(e) => setPoint(e.target.value)} error={Boolean(point) && !pointOk} />
          {error ? <FriendlyError error={error} compact /> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || (!city.trim() && !pointOk)}>{saving ? t("maps.fix.saving") : t("maps.fix.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function PlacesMap({ kind, height = 300 }: { kind: PlaceKind; height?: number }) {
  const t = useT();
  const theme = useTheme();
  const f = theme.palette.fresh;
  const navigate = useNavigate();
  const { can } = useMeBootstrap();
  const ready = useCluster();
  const [config, setConfig] = useState<GeoConfig | null>(null);
  const [data, setData] = useState<PlacesResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [fixing, setFixing] = useState<UnplacedPlace | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setError(null);
    Promise.all([loadConfig(), geoApi.places(kind)]).then(([c, d]) => { if (alive) { setConfig(c); setData(d); } }).catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [kind, tick]);

  // unknown places are looked up online in the background -- check back once shortly after
  useEffect(() => {
    if (!data?.looking_up) return;
    const id = window.setTimeout(() => setTick((x) => x + 1), Math.min(25, 3 + data.looking_up * 1.2) * 1000);
    return () => window.clearTimeout(id);
  }, [data]);

  const countLabel = useCallback((n: number) => t(kind === "offices" ? "maps.people" : "maps.jobs", { count: n }), [t, kind]);
  const onOpen = useCallback((p: { link: string }) => navigate(p.link), [navigate]);
  const points = useMemo(() => (data?.places ?? []).map((p) => [p.lat, p.lng] as [number, number]), [data]);
  const canFix = can(FIX_PERMISSION[kind]);

  if (error) return <FriendlyError error={error} onRetry={() => setTick((x) => x + 1)} compact />;
  if (!data || !config) return <Box sx={{ display: "grid", placeItems: "center", height }}><CircularProgress aria-label={t("maps.loading")} /></Box>;
  if (data.places.length === 0 && data.not_found.length === 0) {
    return <EmptyState compact illustration="empty" title={t(kind === "offices" ? "maps.empty_offices" : "maps.empty_jobs")} />;
  }
  const summary = data.places.map((p) => `${p.label}: ${countLabel(p.count)}`).join(", ");

  return (
    <Box>
      {data.places.length > 0 && (
        <Box role="img" aria-label={summary} sx={{ height, borderRadius: "14px", overflow: "hidden", border: `1px solid ${f.line}`,
          "& .leaflet-container": { bgcolor: f.surface2, fontFamily: "inherit" } }}>
          <MapContainer center={points[0] ?? FALLBACK_CENTER} zoom={5} minZoom={3} style={{ height: "100%", width: "100%" }} scrollWheelZoom
            maxBounds={config.bounds ? latLngBounds(config.bounds).pad(0.3) : undefined} worldCopyJump>
            <TileLayer url={config.tile_url} attribution={config.attribution} />
            <AutoFit points={points} />
            {ready && <Markers places={data.places} colour={f.brand} ink={f.brandInk} countLabel={countLabel} openLabel={t("maps.open_list")} onOpen={onOpen} />}
          </MapContainer>
        </Box>
      )}
      {data.looking_up > 0 && (
        <Typography role="status" sx={{ fontSize: 13, color: f.muted, mt: 1 }}>{t("maps.looking_up", { count: data.looking_up })}</Typography>
      )}
      {data.not_found.length > 0 && (
        <Box sx={{ mt: 1.5 }}>
          <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.75 }}>
            <Emoji name="warning" size={16} />
            <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{t("maps.not_found.title")}</Typography>
          </Stack>
          <Stack spacing={0.75} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
            {data.not_found.map((u) => (
              <Stack component="li" key={u.key} direction="row" spacing={1} alignItems="center"
                sx={{ border: `1px solid ${f.line}`, borderRadius: "10px", px: 1.25, py: 0.75, bgcolor: f.surface2 }}>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>{u.label || t("maps.no_place")}</Typography>
                  <Typography sx={{ fontSize: 12, color: f.muted }}>{countLabel(u.count)} · {t(`maps.reason.${u.reason}`)}</Typography>
                </Box>
                <Button size="small" onClick={() => onOpen(u)}>{t("maps.open_list")}</Button>
                {canFix && u.reason !== "no_place" && <Button size="small" variant="outlined" onClick={() => setFixing(u)}>{t("maps.fix.button")}</Button>}
              </Stack>
            ))}
          </Stack>
        </Box>
      )}
      <FixDialog item={fixing} onClose={() => setFixing(null)} onFixed={() => { setFixing(null); setTick((x) => x + 1); }} />
    </Box>
  );
}
