import "leaflet/dist/leaflet.css";
import { useEffect } from "react";
import { latLngBounds } from "leaflet";
import { CircleMarker, MapContainer, TileLayer, Tooltip as LeafletTooltip, useMap } from "react-leaflet";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate } from "react-router-dom";

import type { Office } from "../../api/homeApi";
import { useT } from "../../i18n";

// Home "People by office": one bubble per office, sized by headcount; click -> the people
// directory filtered to that office (L-V1 click-through to the list).

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 1) map.setView(points[0], 9);
    else if (points.length > 1) map.fitBounds(latLngBounds(points), { padding: [28, 28], maxZoom: 9 });
  }, [map, points]);
  return null;
}

export default function OfficeMap({ offices, height = 220 }: { offices: Office[]; height?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const navigate = useNavigate();
  const placed = offices.filter((o) => o.lat !== null && o.lng !== null);
  const unplaced = offices.filter((o) => o.lat === null || o.lng === null);
  const max = Math.max(1, ...offices.map((o) => o.count));
  const summary = offices.map((o) => `${o.name} ${o.count}`).join(", ");

  return (
    <Box>
      {placed.length > 0 && (
        <Box role="img" aria-label={summary} sx={{ height, borderRadius: "14px", overflow: "hidden", border: `1px solid ${f.line}` }}>
          <MapContainer center={[22.5, 80]} zoom={4} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false} attributionControl>
            <FitBounds points={placed.map((o) => [o.lat as number, o.lng as number])} />
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
            />
            {placed.map((o) => (
              <CircleMarker key={o.id} center={[o.lat as number, o.lng as number]} radius={8 + (o.count / max) * 18}
                pathOptions={{ color: f.brand, fillColor: f.brand, fillOpacity: 0.35, weight: 2 }}
                eventHandlers={{ click: () => navigate(`/directory?location=${encodeURIComponent(o.id)}`) }}>
                <LeafletTooltip>{o.name}: {t("home.offices.people", { count: o.count })}</LeafletTooltip>
              </CircleMarker>
            ))}
          </MapContainer>
        </Box>
      )}
      {unplaced.length > 0 && (
        <Box sx={{ mt: placed.length ? 1.5 : 0 }}>
          {placed.length > 0 && <Typography variant="caption" component="div" sx={{ mb: 0.5 }}>{t("home.offices.no_map")}</Typography>}
          <Stack direction="row" flexWrap="wrap" gap={1}>
            {unplaced.map((o) => (
              <Box key={o.id} component="button" type="button" onClick={() => navigate(`/directory?location=${encodeURIComponent(o.id)}`)}
                sx={{ border: `1px solid ${f.line}`, bgcolor: f.surface2, borderRadius: 999, px: 1.5, py: 0.5, font: "inherit", fontSize: 13, cursor: "pointer", color: f.ink }}>
                <b>{o.name}</b> · {t("home.offices.people", { count: o.count })}
              </Box>
            ))}
          </Stack>
        </Box>
      )}
    </Box>
  );
}
