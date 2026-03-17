import { execFile } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);
const LIVE_TTL_MS = 60_000;

type LivePlanePayload = {
  planeId: string;
  metadata: {
    registration: string;
    aircraftType: string;
  };
  health: Record<string, unknown>;
  prediction: Record<string, unknown>;
  trend: {
    planeId: string;
    points: unknown[];
  };
  history: {
    planeId: string;
    points: unknown[];
  };
  flights: {
    planeId: string;
    flights: unknown[];
  };
  ops?: {
    flightsPerDayRecent?: number;
  };
};

type CacheEntry = {
  expiresAt: number;
  value?: LivePlanePayload;
  promise?: Promise<LivePlanePayload>;
};

const planeCache = new Map<string, CacheEntry>();

function resolveFrontendRoot() {
  const cwd = process.cwd();
  const frontendCwd = path.join(cwd, "frontend");
  if (existsSync(path.join(cwd, "scripts", "live_plane_data.py"))) {
    return cwd;
  }
  if (existsSync(path.join(frontendCwd, "scripts", "live_plane_data.py"))) {
    return frontendCwd;
  }
  throw new Error(`Unable to locate frontend scripts directory from cwd: ${cwd}`);
}

async function runLivePlaneScript(planeId: string): Promise<LivePlanePayload> {
  const frontendRoot = resolveFrontendRoot();
  const scriptPath = path.join(frontendRoot, "scripts", "live_plane_data.py");
  const pythonCommand = process.platform === "win32" ? "python" : "python3";
  const { stdout } = await execFileAsync(
    pythonCommand,
    [scriptPath, "--plane-id", planeId],
    {
      cwd: frontendRoot,
      maxBuffer: 8 * 1024 * 1024
    }
  );

  const parsed = JSON.parse(stdout) as LivePlanePayload;
  if (!parsed || parsed.planeId !== planeId) {
    throw new Error(`Unexpected live payload for plane ${planeId}`);
  }
  return parsed;
}

export async function getLivePlanePayload(planeId: string): Promise<LivePlanePayload> {
  const now = Date.now();
  const cached = planeCache.get(planeId);
  if (cached?.value && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = runLivePlaneScript(planeId)
    .then((value) => {
      planeCache.set(planeId, {
        value,
        expiresAt: Date.now() + LIVE_TTL_MS
      });
      return value;
    })
    .catch((error) => {
      planeCache.delete(planeId);
      throw error;
    });

  planeCache.set(planeId, {
    expiresAt: now + LIVE_TTL_MS,
    promise
  });

  return promise;
}
