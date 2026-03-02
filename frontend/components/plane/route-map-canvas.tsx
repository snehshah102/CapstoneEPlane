"use client";

import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";

type Point = {
  lat: number;
  lon: number;
  label: string;
};

type Props = {
  departure: Point | null;
  destination: Point | null;
};

let iconConfigured = false;

export function RouteMapCanvas({ departure, destination }: Props) {
  const mapHostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlaysRef = useRef<L.LayerGroup | null>(null);

  const center = useMemo<[number, number]>(() => {
    if (departure && destination) {
      return [
        (departure.lat + destination.lat) / 2,
        (departure.lon + destination.lon) / 2
      ];
    }
    if (departure) return [departure.lat, departure.lon];
    if (destination) return [destination.lat, destination.lon];
    return [43.4608, -80.3786];
  }, [departure, destination]);

  const polyline = useMemo<[number, number][]>(() => {
    if (!departure || !destination) return [];
    return [
      [departure.lat, departure.lon],
      [destination.lat, destination.lon]
    ];
  }, [departure, destination]);

  useEffect(() => {
    if (!mapHostRef.current || mapRef.current) return;

    if (!iconConfigured) {
      L.Icon.Default.mergeOptions({
        iconRetinaUrl:
          "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png"
      });
      iconConfigured = true;
    }

    const host = mapHostRef.current as HTMLDivElement & { _leaflet_id?: unknown };
    if (host._leaflet_id) {
      // StrictMode/dev hot-reload can leave a stale id on the container.
      delete host._leaflet_id;
    }

    const map = L.map(host, {
      zoomControl: true,
      attributionControl: true
    }).setView(center, 6);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
    }).addTo(map);

    mapRef.current = map;
    overlaysRef.current = L.layerGroup().addTo(map);

    return () => {
      overlaysRef.current?.clearLayers();
      mapRef.current?.remove();
      overlaysRef.current = null;
      mapRef.current = null;
    };
  }, [center]);

  useEffect(() => {
    const map = mapRef.current;
    const overlays = overlaysRef.current;
    if (!map || !overlays) return;

    overlays.clearLayers();
    map.setView(center, map.getZoom());

    if (departure) {
      L.marker([departure.lat, departure.lon])
        .bindPopup(departure.label)
        .addTo(overlays);
    }
    if (destination) {
      L.marker([destination.lat, destination.lon])
        .bindPopup(destination.label)
        .addTo(overlays);
    }
    if (polyline.length > 1) {
      L.polyline(polyline, { color: "#22d3ee", weight: 4 }).addTo(overlays);
    }
  }, [center, departure, destination, polyline]);

  return (
    <div className="h-[280px] overflow-hidden rounded-xl border border-slate-600/30">
      <div ref={mapHostRef} className="h-full w-full" />
    </div>
  );
}
