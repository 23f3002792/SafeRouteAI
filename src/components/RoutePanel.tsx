import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Navigation, MapPin, Shield, AlertTriangle, Clock, ShieldCheck } from "lucide-react";
import { fetchRouteCompare, type RouteCompareResponse } from "@/lib/api";
import { toast } from "@/hooks/use-toast";

interface RoutePanelProps {
  onRouteResult: (data: RouteCompareResponse | null) => void;
}

const RoutePanel = ({ onRouteResult }: RoutePanelProps) => {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RouteCompareResponse | null>(null);

  const parseCoords = (input: string): [number, number] | null => {
    const parts = input.split(",").map((s) => parseFloat(s.trim()));
    if (parts.length === 2 && parts.every((n) => !isNaN(n))) {
      return [parts[0], parts[1]] as [number, number];
    }
    return null;
  };

  const handleFindRoute = async () => {
    const start = parseCoords(origin);
    const end = parseCoords(destination);

    if (!start || !end) {
      toast({
        title: "Invalid coordinates",
        description: "Enter coordinates as lon,lat (e.g. 78.4867,17.385)",
        variant: "destructive",
      });
      return;
    }

    setLoading(true);
    setResult(null);
    onRouteResult(null);

    try {
      const data = await fetchRouteCompare(start, end);
      setResult(data);
      onRouteResult(data);
    } catch (err: any) {
      toast({
        title: "Route error",
        description: err.message || "Something went wrong",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const formatTime = (s: number) => {
    const mins = Math.round(s / 60);
    return mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)}h ${mins % 60}m`;
  };

  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="fixed top-6 left-1/2 -translate-x-1/2 w-[calc(100%-2rem)] max-w-[400px] z-[1000]"
    >
      <div className="bg-background/95 backdrop-blur-md border border-border p-5 rounded-lg space-y-4">
        {/* Header */}
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-accent" />
          <h1 className="text-sm font-bold tracking-wide text-foreground uppercase">
            SafeRouteAI
          </h1>
        </div>

        {/* Origin */}
        <div className="space-y-1.5">
          <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-bold">
            Origin (lon, lat)
          </label>
          <div className="relative">
            <Navigation className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-primary" />
            <input
              type="text"
              placeholder="78.4867, 17.385"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              className="w-full bg-input border border-border pl-10 pr-4 py-3 text-sm text-foreground placeholder:text-muted-foreground rounded-md focus:outline-none focus:border-primary transition-colors"
            />
          </div>
        </div>

        {/* Destination */}
        <div className="space-y-1.5">
          <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-bold">
            Destination (lon, lat)
          </label>
          <div className="relative">
            <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-destructive" />
            <input
              type="text"
              placeholder="78.55, 17.45"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              className="w-full bg-input border border-border pl-10 pr-4 py-3 text-sm text-foreground placeholder:text-muted-foreground rounded-md focus:outline-none focus:border-primary transition-colors"
            />
          </div>
        </div>

        {/* Find Route Button */}
        <button
          onClick={handleFindRoute}
          disabled={loading || !origin || !destination}
          className="w-full bg-primary hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed text-primary-foreground py-3.5 text-sm font-bold uppercase tracking-wider rounded-md transition-all active:scale-[0.98] shadow-[0_0_20px_hsla(217,91%,60%,0.25)]"
        >
          {loading ? (
            <div className="flex items-center justify-center gap-2">
              <div className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
              <span>Comparing routes...</span>
            </div>
          ) : (
            "Find Safe Route"
          )}
        </button>

        {/* Loading progress bar */}
        {loading && (
          <div className="h-1 w-full bg-input rounded-full overflow-hidden">
            <motion.div
              initial={{ width: "0%" }}
              animate={{ width: "100%" }}
              transition={{ duration: 3, ease: "linear" }}
              className="h-full bg-accent rounded-full"
            />
          </div>
        )}

        {/* Results */}
        <AnimatePresence>
          {result && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="space-y-3 overflow-hidden"
            >
              {/* Route cards */}
              <div className="grid grid-cols-2 gap-2">
                {/* Safest */}
                <div className="bg-accent/10 border border-accent/30 rounded-md p-3 space-y-1">
                  <div className="flex items-center gap-1.5">
                    <ShieldCheck className="w-3.5 h-3.5 text-accent" />
                    <span className="text-[10px] uppercase tracking-widest text-accent font-bold">Safest</span>
                  </div>
                  <p className="text-lg font-bold text-foreground">
                    {(result.safest.safety_score * 100).toFixed(0)}%
                  </p>
                  <p className="text-xs text-muted-foreground flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatTime(result.safest.eta_seconds)}
                  </p>
                </div>

                {/* Fastest */}
                <div className="bg-destructive/10 border border-destructive/30 rounded-md p-3 space-y-1">
                  <div className="flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5 text-destructive" />
                    <span className="text-[10px] uppercase tracking-widest text-destructive font-bold">Fastest</span>
                  </div>
                  <p className="text-lg font-bold text-foreground">
                    {(result.fastest.safety_score * 100).toFixed(0)}%
                  </p>
                  <p className="text-xs text-muted-foreground flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatTime(result.fastest.eta_seconds)}
                  </p>
                </div>
              </div>

              {/* Delta summary */}
              <div className="bg-secondary/50 rounded-md p-3 text-xs text-muted-foreground space-y-1">
                <p>
                  <span className="text-accent font-semibold">
                    +{(result.delta.safety_improvement * 100).toFixed(0)}%
                  </span>{" "}
                  safer
                </p>
                <p>
                  <span className="text-destructive font-semibold">
                    +{formatTime(result.delta.time_penalty_s)}
                  </span>{" "}
                  longer
                </p>
              </div>

              {/* Legend */}
              <div className="flex gap-4 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-0.5 bg-accent inline-block rounded" /> Safest
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-0.5 bg-destructive inline-block rounded border-dashed" /> Fastest
                </span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <p className="text-[10px] text-muted-foreground text-center tracking-wide">
          Enter coordinates within Hyderabad · [lon, lat] format
        </p>
      </div>
    </motion.div>
  );
};

export default RoutePanel;
