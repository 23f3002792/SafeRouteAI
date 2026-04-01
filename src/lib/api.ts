const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000";

export interface RouteGeometry {
  type: "LineString";
  coordinates: [number, number][]; // [lon, lat]
}

export interface RouteOption {
  eta_seconds: number;
  safety_score: number;
  geometry: RouteGeometry;
}

export interface RouteDelta {
  time_penalty_s: number;
  safety_improvement: number;
}

export interface RouteCompareResponse {
  safest: RouteOption;
  fastest: RouteOption;
  delta: RouteDelta;
}

export async function fetchRouteCompare(
  start: [number, number],
  end: [number, number]
): Promise<RouteCompareResponse> {
  const res = await fetch(`${API_BASE}/api/v1/route/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start, end }),
  });

  if (!res.ok) {
    if (res.status === 400) throw new Error("Invalid coordinates or out of Hyderabad bounds.");
    if (res.status === 503) throw new Error("Routing service temporarily unavailable.");
    throw new Error(`Request failed (${res.status})`);
  }

  return res.json();
}
