export type AirportMeta = {
  icao: string;
  name: string;
  lat: number;
  lon: number;
  state: string;
  country: "US" | "CA" | "ZA";
};

export const AIRPORTS: Record<string, AirportMeta> = {
  CYKF: {
    icao: "CYKF",
    name: "Kitchener/Waterloo",
    lat: 43.4608,
    lon: -80.3786,
    state: "ON",
    country: "CA"
  },
  CYFD: {
    icao: "CYFD",
    name: "Brantford Airport",
    lat: 43.1314,
    lon: -80.3425,
    state: "ON",
    country: "CA"
  },
  CYBL: {
    icao: "CYBL",
    name: "Campbell River",
    lat: 49.9508,
    lon: -125.2708,
    state: "BC",
    country: "CA"
  },
  FAPA: {
    icao: "FAPA",
    name: "Port Alfred Airport",
    lat: -33.56,
    lon: 26.88,
    state: "EC",
    country: "ZA"
  },
  CYPK: {
    icao: "CYPK",
    name: "Pitt Meadows",
    lat: 49.2161,
    lon: -122.71,
    state: "BC",
    country: "CA"
  }
};

export function airportFromLabel(label: string | null | undefined) {
  if (!label) return null;
  const code = label.slice(0, 4).toUpperCase();
  return AIRPORTS[code] ?? null;
}
