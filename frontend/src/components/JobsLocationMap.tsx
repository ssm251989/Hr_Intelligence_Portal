import "leaflet/dist/leaflet.css";
import { CircleMarker, MapContainer, TileLayer, Tooltip as LeafletTooltip } from "react-leaflet";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";

// Small curated lookup, not a live geocoding service -- there's no API key and no
// geocoding budget here. Locations that don't match (e.g. "Remote", or a city not in
// this list) are listed separately below the map rather than guessed at or dropped
// silently. Covers India's major metros + state capitals, since that's where this
// app's real data lives; extend this table as new cities show up in practice.
const CITY_COORDINATES: Record<string, [number, number]> = {
  mumbai: [19.076, 72.8777],
  delhi: [28.7041, 77.1025],
  "new delhi": [28.6139, 77.209],
  bangalore: [12.9716, 77.5946],
  bengaluru: [12.9716, 77.5946],
  hyderabad: [17.385, 78.4867],
  chennai: [13.0827, 80.2707],
  kolkata: [22.5726, 88.3639],
  pune: [18.5204, 73.8567],
  ahmedabad: [23.0225, 72.5714],
  jaipur: [26.9124, 75.7873],
  surat: [21.1702, 72.8311],
  lucknow: [26.8467, 80.9462],
  kanpur: [26.4499, 80.3319],
  nagpur: [21.1458, 79.0882],
  indore: [22.7196, 75.8577],
  thane: [19.2183, 72.9781],
  bhopal: [23.2599, 77.4126],
  visakhapatnam: [17.6868, 83.2185],
  vadodara: [22.3072, 73.1812],
  patna: [25.5941, 85.1376],
  ghaziabad: [28.6692, 77.4538],
  ludhiana: [30.901, 75.8573],
  agra: [27.1767, 78.0081],
  nashik: [19.9975, 73.7898],
  faridabad: [28.4089, 77.3178],
  meerut: [28.9845, 77.7064],
  rajkot: [22.3039, 70.8022],
  varanasi: [25.3176, 82.9739],
  srinagar: [34.0837, 74.7973],
  amritsar: [31.634, 74.8723],
  coimbatore: [11.0168, 76.9558],
  madurai: [9.9252, 78.1198],
  kochi: [9.9312, 76.2673],
  cochin: [9.9312, 76.2673],
  thiruvananthapuram: [8.5241, 76.9366],
  trivandrum: [8.5241, 76.9366],
  guwahati: [26.1445, 91.7362],
  chandigarh: [30.7333, 76.7794],
  bhubaneswar: [20.2961, 85.8245],
  raipur: [21.2514, 81.6296],
  ranchi: [23.3441, 85.3096],
  dehradun: [30.3165, 78.0322],
  gurugram: [28.4595, 77.0266],
  gurgaon: [28.4595, 77.0266],
  noida: [28.5355, 77.391],
  mysore: [12.2958, 76.6394],
  mysuru: [12.2958, 76.6394],
  kurnool: [15.8281, 78.0373],
  vijayawada: [16.5062, 80.648],
  tirupati: [13.6288, 79.4192],
  warangal: [17.9689, 79.5941],
  mangalore: [12.9141, 74.856],
  jodhpur: [26.2389, 73.0243],
  udaipur: [24.5854, 73.7125],
  goa: [15.2993, 74.124],
  panaji: [15.4909, 73.8278],
};

const CATEGORICAL_BLUE = "#2a78d6";

function resolveCoordinates(location: string): [number, number] | null {
  return CITY_COORDINATES[location.trim().toLowerCase()] ?? null;
}

export default function JobsLocationMap({ rows }: { rows: LabeledCount[] }) {
  const resolved = rows
    .map((row) => ({ ...row, coords: resolveCoordinates(row.label) }))
    .filter((row): row is LabeledCount & { coords: [number, number] } => row.coords !== null);
  const unresolved = rows.filter((row) => resolveCoordinates(row.label) === null);
  const maxCount = Math.max(...rows.map((row) => row.count), 1);

  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No jobs yet.
      </Typography>
    );
  }

  return (
    <Box>
      <Box sx={{ height: 280, borderRadius: 1, overflow: "hidden" }}>
        <MapContainer center={[22.5, 79]} zoom={4.5} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          />
          {resolved.map((row) => (
            <CircleMarker
              key={row.label}
              center={row.coords}
              radius={8 + (row.count / maxCount) * 16}
              pathOptions={{ color: CATEGORICAL_BLUE, fillColor: CATEGORICAL_BLUE, fillOpacity: 0.55, weight: 1 }}
            >
              <LeafletTooltip>
                {row.label}: {row.count} {row.count === 1 ? "job" : "jobs"}
              </LeafletTooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </Box>
      {unresolved.length > 0 && (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mt={1}>
          <Typography variant="caption" color="text.secondary">
            Not shown on map (unrecognized location):
          </Typography>
          {unresolved.map((row) => (
            <Typography key={row.label} variant="caption" color="text.secondary">
              {row.label} ({row.count})
            </Typography>
          ))}
        </Stack>
      )}
    </Box>
  );
}
