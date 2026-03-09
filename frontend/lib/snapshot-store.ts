import { promises as fs } from "fs";
import path from "path";

const SNAPSHOT_DIR = path.join(process.cwd(), "public", "snapshots");
const PARSE_RETRY_DELAY_MS = 30;

function isSyntaxError(error: unknown): boolean {
  return error instanceof SyntaxError;
}

async function wait(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function readJson<T>(filename: string): Promise<T> {
  const fullPath = path.join(SNAPSHOT_DIR, filename);
  try {
    const raw = await fs.readFile(fullPath, "utf8");
    return JSON.parse(raw) as T;
  } catch (error) {
    if (!isSyntaxError(error)) {
      throw error;
    }
    await wait(PARSE_RETRY_DELAY_MS);
    const retryRaw = await fs.readFile(fullPath, "utf8");
    return JSON.parse(retryRaw) as T;
  }
}

export async function readPlanesSnapshot() {
  return readJson<{ planes: unknown[] }>("planes.json");
}

export async function readPlaneKpisSnapshot(planeId: string) {
  return readJson<{ health: unknown; prediction: unknown }>(
    `plane_${planeId}_kpis.json`
  );
}

export async function readPlaneTrendSnapshot(planeId: string) {
  return readJson<{ planeId: string; points: unknown[] }>(
    `plane_${planeId}_soh_trend.json`
  );
}

export async function readPlaneHistorySnapshot(planeId: string) {
  return readJson<{ planeId: string; points: unknown[] }>(
    `plane_${planeId}_soh_history.json`
  );
}

export async function readPlaneFlightsSnapshot(planeId: string) {
  return readJson<{ planeId: string; flights: unknown[] }>(
    `plane_${planeId}_flights.json`
  );
}

export async function readPlaneRecommendationsSnapshot(
  planeId: string,
  month: string
) {
  const normalizedMonth = month.replace("-", "_");
  const preferred = path.join(
    SNAPSHOT_DIR,
    `plane_${planeId}_recommendations_${normalizedMonth}.json`
  );

  try {
    return await readJson<{ recommendations: unknown }>(
      `plane_${planeId}_recommendations_${normalizedMonth}.json`
    );
  } catch {
    const entries = await fs.readdir(SNAPSHOT_DIR);
    const fallbackFile = entries.find(
      (file) =>
        file.startsWith(`plane_${planeId}_recommendations_`) &&
        file.endsWith(".json")
    );
    if (!fallbackFile) {
      throw new Error(`No recommendations found for plane ${planeId}`);
    }
    return readJson<{ recommendations: unknown }>(fallbackFile);
  }
}

export async function readGlossarySnapshot() {
  return readJson<{ version: string; items: unknown[] }>("glossary.json");
}

export async function readLearnBaselineSnapshot(planeId: string) {
  const preferred = path.join(SNAPSHOT_DIR, `learn_baseline_plane_${planeId}.json`);
  try {
    return await readJson<{ baseline: unknown }>(
      `learn_baseline_plane_${planeId}.json`
    );
  } catch {
    const entries = await fs.readdir(SNAPSHOT_DIR);
    const fallbackFile = entries.find(
      (file) =>
        file.startsWith("learn_baseline_plane_") && file.endsWith(".json")
    );
    if (!fallbackFile) {
      throw new Error("No learn baseline snapshots found");
    }
    return readJson<{ baseline: unknown }>(fallbackFile);
  }
}
