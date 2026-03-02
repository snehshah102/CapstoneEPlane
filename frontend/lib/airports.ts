export type AirportMeta = {
  icao: string;
  name: string;
  lat: number;
  lon: number;
};

export const AIRPORTS: Record<string, AirportMeta> = {
  CYKF: { icao: "CYKF", name: "Kitchener/Waterloo", lat: 43.4608, lon: -80.3786 },
  CYFD: { icao: "CYFD", name: "Brantford Airport", lat: 43.1314, lon: -80.3425 },
  CYBL: { icao: "CYBL", name: "Campbell River", lat: 49.9508, lon: -125.2708 },
  FAPA: { icao: "FAPA", name: "Port Alfred Airport", lat: -33.56, lon: 26.88 },
  CYPK: { icao: "CYPK", name: "Pitt Meadows", lat: 49.2161, lon: -122.71 }
};

export function airportFromLabel(label: string | null | undefined) {
  if (!label) return null;
  const code = label.slice(0, 4).toUpperCase();
  return AIRPORTS[code] ?? null;
}
