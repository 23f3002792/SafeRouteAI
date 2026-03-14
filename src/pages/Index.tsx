import MapView from "@/components/MapView";
import RoutePanel from "@/components/RoutePanel";

const Index = () => {
  return (
    <div className="relative h-svh w-full overflow-hidden">
      <MapView />
      <RoutePanel />
    </div>
  );
};

export default Index;
