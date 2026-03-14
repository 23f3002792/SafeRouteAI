import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const HYD_COORDS: L.LatLngExpression = [17.385, 78.4867];

const MapView = () => {
  const mapRef = useRef<L.Map | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: false,
    }).setView(HYD_COORDS, 13);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);

    L.control.zoom({ position: "bottomright" }).addTo(map);

    // Custom location marker
    const locationIcon = L.divIcon({
      className: "",
      html: '<div class="location-dot"></div>',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });

    L.marker(HYD_COORDS, { icon: locationIcon }).addTo(map);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className="h-svh w-full" />;
};

export default MapView;
