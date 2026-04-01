import { useState } from "react";
import MapView from "@/components/MapView";
import RoutePanel from "@/components/RoutePanel";
import type { RouteCompareResponse } from "@/lib/api";

const Index = () => {
  const [routeData, setRouteData] = useState<RouteCompareResponse | null>(null);

  return (
    <div className="relative h-svh w-full overflow-hidden">
      <MapView routeData={routeData} />
      <RoutePanel onRouteResult={setRouteData} />
    </div>
  );
};

export default Index;
