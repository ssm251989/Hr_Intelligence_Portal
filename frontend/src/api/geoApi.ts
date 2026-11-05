// Part 17.3 -- map data (backend/app/experience/geo_router.py).
import { http } from "./client";

export type PlaceKind = "offices" | "jobs";

export interface GeoConfig {
  tile_url: string;
  attribution: string;
  countries: string[];
  bounds: [[number, number], [number, number]] | null;
}

export interface PlaceFix { kind: PlaceKind; text: string; location_id?: string }

export interface MapPlace {
  key: string;
  label: string | null;
  count: number;
  lat: number;
  lng: number;
  source: "record" | "manual" | "offline" | "nominatim";
  link: string;
  fix: PlaceFix;
}

export interface UnplacedPlace {
  key: string;
  label: string | null;
  count: number;
  link: string;
  fix: PlaceFix;
  reason: "pending" | "not_found" | "outside" | "no_place";
}

export interface PlacesResult { kind: PlaceKind; places: MapPlace[]; not_found: UnplacedPlace[]; looking_up: number; total: number }

export const geoApi = {
  config: () => http.get<GeoConfig>("/api/v1/geo/config"),
  places: (kind: PlaceKind) => http.get<PlacesResult>(`/api/v1/geo/places?kind=${kind}`),
  fix: (payload: PlaceFix & { city?: string; lat?: number; lng?: number }) =>
    http.put<{ text: string; lat: number; lng: number; label: string; source: string }>("/api/v1/geo/fix", payload),
};
