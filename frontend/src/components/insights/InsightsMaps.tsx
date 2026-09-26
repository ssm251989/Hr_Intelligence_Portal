import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import L, { latLngBounds } from "leaflet";
import { CircleMarker, MapContainer, TileLayer, Tooltip as LeafletTooltip, useMap } from "react-leaflet";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate } from "react-router-dom";

import type { Office } from "../../api/homeApi";
import type { HeatCell, JobLocation } from "../../api/insightsApi";
import { useT } from "../../i18n";

// Part 15.6 L-V1/V2/V3: the three Analytics maps. This whole file is lazy-loaded by the
// Analytics page, so Leaflet and its plugins only download when someone opens it.
// Every map also lists its places as plain buttons underneath (screen readers + places we
// can't put on the map), and every place clicks through to the matching filtered list.

// leaflet.heat is a plain browser script that extends the global `L`.
let pluginsReady: Promise<void> | null = null;
function loadPlugins(): Promise<void> {
  pluginsReady ??= (async () => {
    (window as unknown as { L: typeof L }).L = L;
    await import("leaflet.markercluster");
    await import("leaflet.heat");
  })();
  return pluginsReady;
}

function usePlugins(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    loadPlugins().then(() => alive && setReady(true)).catch(() => alive && setReady(false));
    return () => {
      alive = false;
    };
  }, []);
  return ready;
}

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  const key = JSON.stringify(points); // refit only when the places change, not on every render
  useEffect(() => {
    const pts = JSON.parse(key) as [number, number][];
    const frame = requestAnimationFrame(() => {
      map.invalidateSize();
      if (pts.length === 1) map.setView(pts[0], 8);
      else if (pts.length > 1) map.fitBounds(latLngBounds(pts), { padding: [28, 28], maxZoom: 8 });
    });
    return () => cancelAnimationFrame(frame);
  }, [map, key]);
  return null;
}

function BaseMap({ points, height, label, children }: { points: [number, number][]; height: number; label: string; children: ReactNode }) {
  const theme = useTheme();
  const f = theme.palette.fresh;
  const style = theme.palette.mode === "dark" ? "dark_all" : "light_all";
  return (
    <Box role="img" aria-label={label} sx={{ height, borderRadius: "14px", overflow: "hidden", border: `1px solid ${f.line}`, "& .leaflet-container": { bgcolor: f.surface2, fontFamily: "inherit" } }}>
      <MapContainer center={[22.5, 80]} zoom={4} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
        <FitBounds points={points} />
        <TileLayer
          url={`https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
        />
        {children}
      </MapContainer>
    </Box>
  );
}

function PlaceChips({ items, onPick }: { items: { key: string; label: string; count: string }[]; onPick: (key: string) => void }) {
  const f = useTheme().palette.fresh;
  if (!items.length) return null;
  return (
    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1.5 }}>
      {items.map((it) => (
        <Box key={it.key} component="button" type="button" onClick={() => onPick(it.key)}
          sx={{ border: `1px solid ${f.line}`, bgcolor: f.surface2, borderRadius: 999, px: 1.5, py: 0.5, font: "inherit", fontSize: 13, cursor: "pointer", color: f.ink,
            "&:hover": { borderColor: f.brand }, "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 2 } }}>
          <b>{it.label}</b> · {it.count}
        </Box>
      ))}
    </Stack>
  );
}

// ---- L-V1: open jobs by location ----

export function JobsMap({ locations, height = 300 }: { locations: JobLocation[]; height?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const chart = useTheme().palette.chart;
  const navigate = useNavigate();
  const placed = locations.filter((l) => l.lat !== null && l.lng !== null);
  const max = Math.max(1, ...locations.map((l) => l.count));
  const open = (loc: string | null) => navigate(`/jobs?status=published${loc ? `&location=${encodeURIComponent(loc)}` : ""}`);
  const label = (l: JobLocation) => l.location || t("analytics.maps.no_location");
  const summary = locations.map((l) => `${label(l)}: ${t("analytics.maps.jobs", { count: l.count })}`).join(", ");

  return (
    <Box>
      {placed.length > 0 && (
        <BaseMap points={placed.map((l) => [l.lat!, l.lng!])} height={height} label={summary}>
          {placed.map((l) => (
            <CircleMarker key={`${l.location}`} center={[l.lat!, l.lng!]} radius={7 + (l.count / max) * 14}
              pathOptions={{ color: chart[0] ?? f.brand, fillColor: chart[0] ?? f.brand, fillOpacity: 0.4, weight: 2 }}
              eventHandlers={{ click: () => open(l.location) }}>
              <LeafletTooltip>{label(l)}: {t("analytics.maps.jobs", { count: l.count })}</LeafletTooltip>
            </CircleMarker>
          ))}
        </BaseMap>
      )}
      <PlaceChips items={locations.map((l) => ({ key: l.location ?? "", label: label(l), count: t("analytics.maps.jobs", { count: l.count }) }))}
        onPick={(k) => open(k || null)} />
    </Box>
  );
}

// ---- L-V2: candidate heat-map (city level, min 5 per cell -- enforced by the server) ----

function HeatLayer({ cells, gradient }: { cells: HeatCell[]; gradient: Record<number, string> }) {
  const map = useMap();
  useEffect(() => {
    const max = Math.max(1, ...cells.map((c) => c.count));
    const layer = L.heatLayer(cells.map((c) => [c.lat!, c.lng!, c.count / max] as [number, number, number]), { radius: 32, blur: 24, maxZoom: 8, gradient });
    layer.addTo(map);
    return () => {
      layer.remove();
    };
  }, [map, cells, gradient]);
  return null;
}

export function CandidateHeatMap({ cells, height = 300 }: { cells: HeatCell[]; height?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const navigate = useNavigate();
  const ready = usePlugins();
  const placed = useMemo(() => cells.filter((c) => c.lat !== null && c.lng !== null), [cells]);
  const open = (city: string) => navigate(`/candidates/list?location=${encodeURIComponent(city)}`);
  const summary = cells.map((c) => `${c.city}: ${t("analytics.maps.candidates", { count: c.count })}`).join(", ");
  const gradient = useMemo(() => ({ 0.2: f.sky, 0.5: f.brand, 0.8: f.sun, 1: f.coral }), [f]);

  return (
    <Box>
      {placed.length > 0 && (
        <BaseMap points={placed.map((c) => [c.lat!, c.lng!])} height={height} label={summary}>
          {ready && <HeatLayer cells={placed} gradient={gradient} />}
          {/* invisible hit-targets so each hot spot can be hovered and clicked */}
          {placed.map((c) => (
            <CircleMarker key={c.city} center={[c.lat!, c.lng!]} radius={16} pathOptions={{ opacity: 0, fillOpacity: 0 }}
              eventHandlers={{ click: () => open(c.city) }}>
              <LeafletTooltip>{c.city}: {t("analytics.maps.candidates", { count: c.count })}</LeafletTooltip>
            </CircleMarker>
          ))}
        </BaseMap>
      )}
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
        <Typography variant="caption">{t("analytics.maps.fewer")}</Typography>
        <Box aria-hidden sx={{ width: 90, height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${f.sky}, ${f.brand}, ${f.sun}, ${f.coral})` }} />
        <Typography variant="caption">{t("analytics.maps.more")}</Typography>
      </Stack>
      <PlaceChips items={cells.map((c) => ({ key: c.city, label: c.city, count: t("analytics.maps.candidates", { count: c.count }) }))} onPick={open} />
    </Box>
  );
}

// ---- L-V3: headcount by office with marker clusters (clusters add up their offices) ----

function ClusterLayer({ offices, colour, ink, onPick, peopleLabel }: {
  offices: Office[]; colour: string; ink: string; onPick: (id: string) => void; peopleLabel: (n: number) => string;
}) {
  const map = useMap();
  useEffect(() => {
    const bubble = (n: number, size: number) =>
      L.divIcon({
        html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${colour};color:${ink};display:grid;place-items:center;font-weight:800;font-size:13px;box-shadow:0 0 0 5px ${colour}55">${n}</div>`,
        className: "", iconSize: [size, size],
      });
    const group = L.markerClusterGroup({
      showCoverageOnHover: false, maxClusterRadius: 50,
      iconCreateFunction: (cluster) => {
        const sum = cluster.getAllChildMarkers().reduce((acc, m) => acc + ((m.options as { count?: number }).count ?? 0), 0);
        return bubble(sum, 40);
      },
    });
    offices.filter((o) => o.lat !== null && o.lng !== null).forEach((o) => {
      const marker = L.marker([o.lat!, o.lng!], { icon: bubble(o.count, 32), count: o.count, keyboard: true, title: `${o.name}: ${peopleLabel(o.count)}` } as L.MarkerOptions & { count: number });
      marker.bindTooltip(`${o.name}: ${peopleLabel(o.count)}`);
      marker.on("click", () => onPick(o.id));
      group.addLayer(marker);
    });
    map.addLayer(group);
    return () => {
      map.removeLayer(group);
    };
  }, [map, offices, colour, ink, onPick, peopleLabel]);
  return null;
}

export function HeadcountClusterMap({ offices, height = 300 }: { offices: Office[]; height?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const navigate = useNavigate();
  const ready = usePlugins();
  const placed = useMemo(() => offices.filter((o) => o.lat !== null && o.lng !== null), [offices]);
  const open = useCallback((id: string) => navigate(`/directory?location=${encodeURIComponent(id)}`), [navigate]);
  const people = useCallback((n: number) => t("analytics.maps.people", { count: n }), [t]);
  const summary = offices.map((o) => `${o.name}: ${people(o.count)}`).join(", ");

  return (
    <Box>
      {placed.length > 0 && (
        <BaseMap points={placed.map((o) => [o.lat!, o.lng!])} height={height} label={summary}>
          {ready && <ClusterLayer offices={placed} colour={f.brand} ink={f.brandInk} onPick={open} peopleLabel={people} />}
        </BaseMap>
      )}
      <PlaceChips items={offices.map((o) => ({ key: o.id, label: o.name, count: people(o.count) }))} onPick={open} />
    </Box>
  );
}
