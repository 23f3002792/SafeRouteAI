import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { RouteCompareResponse } from "@/lib/api";

const HYD_COORDS: L.LatLngExpression = [17.385, 78.4867];

interface MapViewProps {
  routeData: RouteCompareResponse | null;
}

const MapView = ({ routeData }: MapViewProps) => {
  const mapRef = useRef<L.Map | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const layersRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: false,
    }).setView(HYD_COORDS, 13);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);

    const locationIcon = L.divIcon({
      className: "",
      html: '<div class="location-dot"></div>',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });

    L.marker(HYD_COORDS, { icon: locationIcon }).addTo(map);

    layersRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Draw routes when routeData changes
  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;

    layers.clearLayers();

    if (!routeData) return;

    const toLatLngs = (coords: [number, number][]): L.LatLngExpression[] =>
      coords.map(([lon, lat]) => [lat, lon]);

    // Fastest route (red, drawn first so safest renders on top)
    const fastestLine = L.polyline(toLatLngs(routeData.fastest.geometry.coordinates), {
      color: "hsl(0, 84%, 60%)",
      weight: 5,
      opacity: 0.7,
      dashArray: "8 6",
    });
    layers.addLayer(fastestLine);

    // Safest route (green)
    const safestLine = L.polyline(toLatLngs(routeData.safest.geometry.coordinates), {
      color: "hsl(142, 70%, 45%)",
      weight: 5,
      opacity: 0.9,
    });
    layers.addLayer(safestLine);

    // Fit map to show both routes
    const bounds = L.featureGroup([fastestLine, safestLine]).getBounds();
    map.fitBounds(bounds, { padding: [60, 60] });
  }, [routeData]);

  return <div ref={containerRef} className="h-svh w-full" />;
};

export default MapView;
