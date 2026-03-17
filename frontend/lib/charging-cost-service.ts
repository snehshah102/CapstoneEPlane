import { AIRPORTS } from "@/lib/airports";
import { ChargingCostResponseSchema } from "@/lib/contracts/schemas";

const USD_PER_CAD = 0.74;
const USD_PER_ZAR = 0.054;
const REMOTE_CACHE_TTL_MS = 15 * 60_000;

type CachedText = {
  expiresAt: number;
  value?: string | null;
  promise?: Promise<string | null>;
};

const remoteTextCache = new Map<string, CachedText>();

export function fallbackRateUsdPerKwh(state: string, country: "US" | "CA" | "ZA") {
  if (country === "US") {
    return 0.17;
  }
  if (country === "CA" && state === "ON") {
    return Number(((9.8 / 100) * USD_PER_CAD).toFixed(3));
  }
  if (country === "CA" && state === "BC") {
    return Number(((13.98 / 100) * USD_PER_CAD).toFixed(3));
  }
  if (country === "ZA") {
    return Number((2.4482 * USD_PER_ZAR).toFixed(3));
  }
  return country === "CA" ? 0.11 : 0.13;
}

function formatDateInTimeZone(date: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(date);
  const year = parts.find((part) => part.type === "year")?.value ?? "1970";
  const month = parts.find((part) => part.type === "month")?.value ?? "01";
  const day = parts.find((part) => part.type === "day")?.value ?? "01";
  return `${year}-${month}-${day}`;
}

function hourInTimeZone(date: Date, timeZone: string) {
  const hour = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "2-digit",
    hour12: false
  }).format(date);
  return Number(hour);
}

async function fetchText(url: string, cacheKey: string) {
  const now = Date.now();
  const cached = remoteTextCache.get(cacheKey);
  if (cached?.value !== undefined && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4_000);
  const promise = fetch(url, {
    cache: "no-store",
    signal: controller.signal
  })
    .then(async (response) => {
      if (!response.ok) {
        return null;
      }
      return response.text();
    })
    .catch(() => null)
    .finally(() => {
      clearTimeout(timeout);
    });

  remoteTextCache.set(cacheKey, {
    expiresAt: now + REMOTE_CACHE_TTL_MS,
    promise
  });

  const value = await promise;
  remoteTextCache.set(cacheKey, {
    expiresAt: Date.now() + REMOTE_CACHE_TTL_MS,
    value
  });
  return value;
}

async function fetchEiaRateUsdPerKwh(state: string) {
  const apiKey = process.env.EIA_API_KEY;
  if (!apiKey) return null;

  const params = new URLSearchParams({
    frequency: "monthly",
    "data[0]": "price",
    "facets[stateid][]": state,
    "facets[sectorid][]": "RES",
    "sort[0][column]": "period",
    "sort[0][direction]": "desc",
    offset: "0",
    length: "1",
    api_key: apiKey
  });

  const text = await fetchText(
    `https://api.eia.gov/v2/electricity/retail-sales/data/?${params.toString()}`,
    `eia:${state}`
  );
  if (!text) return null;

  try {
    const payload = JSON.parse(text) as {
      response?: { data?: Array<{ price?: string | number }> };
    };
    const rawPrice = payload.response?.data?.[0]?.price;
    const numeric = Number(rawPrice);
    if (!Number.isFinite(numeric) || numeric <= 0) return null;
    return Number((numeric > 1 ? numeric / 100 : numeric).toFixed(3));
  } catch {
    return null;
  }
}

function parseOntarioTouRates(html: string) {
  const touSection =
    html.match(
      /<p><strong>Time-of-Use \(TOU\)<\/strong><\/p><table[\s\S]*?<\/table>/i
    )?.[0] ?? "";
  if (!touSection) {
    return null;
  }

  const offPeak = Number(
    touSection.match(
      /<strong>Off-Peak<\/strong>[\s\S]*?text-align-center"><strong>([\d.]+)<\/strong>/i
    )?.[1]
  );
  const midPeak = Number(
    touSection.match(
      /<strong>Mid-Peak<\/strong>[\s\S]*?text-align-center"><strong>([\d.]+)<\/strong>/i
    )?.[1]
  );
  const onPeak = Number(
    touSection.match(
      /<strong>On-Peak<\/strong>[\s\S]*?text-align-center"><strong>([\d.]+)<\/strong>/i
    )?.[1]
  );

  if (![offPeak, midPeak, onPeak].every((value) => Number.isFinite(value) && value > 0)) {
    return null;
  }

  return { offPeak, midPeak, onPeak };
}

function ontarioTouBucket(dateIso: string) {
  const target = new Date(`${dateIso}T12:00:00Z`);
  const weekday = target.getUTCDay();
  if (weekday === 0 || weekday === 6) {
    return "offPeak" as const;
  }

  const torontoTodayIso = formatDateInTimeZone(new Date(), "America/Toronto");
  const localHour = dateIso === torontoTodayIso ? hourInTimeZone(new Date(), "America/Toronto") : 19;
  const month = Number(dateIso.slice(5, 7));
  const winter = month <= 4 || month >= 11;

  if (winter) {
    if ((localHour >= 7 && localHour < 11) || (localHour >= 17 && localHour < 19)) {
      return "onPeak" as const;
    }
    if (localHour >= 11 && localHour < 17) {
      return "midPeak" as const;
    }
    return "offPeak" as const;
  }

  if (localHour >= 11 && localHour < 17) {
    return "onPeak" as const;
  }
  if ((localHour >= 7 && localHour < 11) || (localHour >= 17 && localHour < 19)) {
    return "midPeak" as const;
  }
  return "offPeak" as const;
}

async function fetchOntarioRateUsdPerKwh(dateIso: string) {
  const html = await fetchText(
    "https://www.oeb.ca/consumer-information-and-protection/electricity-rates",
    "oeb:rates"
  );
  if (!html) return null;

  const rates = parseOntarioTouRates(html);
  if (!rates) return null;

  const bucket = ontarioTouBucket(dateIso);
  const centsPerKwh = rates[bucket];
  return Number((((centsPerKwh ?? 0) / 100) * USD_PER_CAD).toFixed(3));
}

async function fetchBcRateUsdPerKwh() {
  const html = await fetchText(
    "https://www.bchydro.com/accounts-billing/rates-energy-use/electricity-rates/business-rates.html",
    "bchydro:business-rates"
  );
  if (!html) return null;

  const centsPerKwh = Number(
    html.match(/<td>\s*([\d.]+)\s*cents per kWh\.\s*<\/td>/i)?.[1]
  );
  if (!Number.isFinite(centsPerKwh) || centsPerKwh <= 0) {
    return null;
  }

  return Number(((centsPerKwh / 100) * USD_PER_CAD).toFixed(3));
}

async function fetchLiveRateUsdPerKwh(
  state: string,
  country: "US" | "CA" | "ZA",
  dateIso: string
) {
  if (country === "US") {
    return fetchEiaRateUsdPerKwh(state);
  }
  if (country === "CA" && state === "ON") {
    return fetchOntarioRateUsdPerKwh(dateIso);
  }
  if (country === "CA" && state === "BC") {
    return fetchBcRateUsdPerKwh();
  }
  return null;
}

export async function getChargingCostEstimatePayload(
  airport: string,
  date: string,
  energyKwh: number
) {
  const airportCode = airport.slice(0, 4).toUpperCase();
  const airportMeta = AIRPORTS[airportCode];
  if (!airportMeta) {
    throw new Error(`Unsupported airport code ${airportCode}`);
  }

  const liveRate = await fetchLiveRateUsdPerKwh(
    airportMeta.state,
    airportMeta.country,
    date
  );
  const costPerKwhUsd =
    liveRate ?? fallbackRateUsdPerKwh(airportMeta.state, airportMeta.country);

  return ChargingCostResponseSchema.parse({
    estimate: {
      airport: airportCode,
      state: airportMeta.state,
      costPerKwhUsd,
      estimatedSessionCostUsd: Number((costPerKwhUsd * energyKwh).toFixed(2)),
      energyKwh,
      sourceMode: liveRate ? "live" : "fallback",
      generatedAt: new Date(`${date}T00:00:00Z`).toISOString()
    }
  });
}
