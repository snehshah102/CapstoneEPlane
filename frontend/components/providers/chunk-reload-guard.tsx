"use client";

import { useEffect } from "react";

const RELOAD_KEY = "aerocell_chunk_reload_once";

function shouldHandleChunkError(message: string) {
  const lower = message.toLowerCase();
  return (
    lower.includes("chunkloaderror") ||
    lower.includes("loading chunk") ||
    lower.includes("failed to fetch dynamically imported module") ||
    (lower.includes("__webpack_modules__") && lower.includes("not a function")) ||
    (lower.includes("webpack_modules") && lower.includes("not a function"))
  );
}

export function ChunkReloadGuard() {
  useEffect(() => {
    const maybeReload = (message: string) => {
      if (!shouldHandleChunkError(message)) return;

      const hasReloaded = sessionStorage.getItem(RELOAD_KEY) === "1";
      if (hasReloaded) return;

      sessionStorage.setItem(RELOAD_KEY, "1");
      window.location.reload();
    };

    const onError = (event: ErrorEvent) => {
      if (!event.message) return;
      maybeReload(event.message);
    };

    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      const message =
        typeof reason === "string"
          ? reason
          : reason?.message ?? reason?.toString?.() ?? "";
      if (!message) return;
      maybeReload(message);
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, []);

  return null;
}
