import { useState } from "react";
import { motion } from "framer-motion";
import { Navigation, MapPin, Shield } from "lucide-react";

const modeOptions = [
  { value: "safest", label: "Safest" },
  { value: "balanced", label: "Balanced" },
  { value: "fastest", label: "Fastest" },
] as const;

type SafetyMode = (typeof modeOptions)[number]["value"];

const RoutePanel = () => {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [mode, setMode] = useState<SafetyMode>("safest");
  const [loading, setLoading] = useState(false);

  const handleFindRoute = () => {
    if (!origin || !destination) return;
    setLoading(true);
    // Simulate API call
    setTimeout(() => setLoading(false), 2000);
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
            Origin
          </label>
          <div className="relative">
            <Navigation className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-primary" />
            <input
              type="text"
              placeholder="Current location or search..."
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              className="w-full bg-input border border-border pl-10 pr-4 py-3 text-sm text-foreground placeholder:text-muted-foreground rounded-md focus:outline-none focus:border-primary transition-colors"
            />
          </div>
        </div>

        {/* Destination */}
        <div className="space-y-1.5">
          <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-bold">
            Destination
          </label>
          <div className="relative">
            <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-destructive" />
            <input
              type="text"
              placeholder="Enter destination in Hyderabad..."
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              className="w-full bg-input border border-border pl-10 pr-4 py-3 text-sm text-foreground placeholder:text-muted-foreground rounded-md focus:outline-none focus:border-primary transition-colors"
            />
          </div>
        </div>

        {/* Mode Selector */}
        <div className="space-y-1.5">
          <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-bold">
            Safety Mode
          </label>
          <div className="flex gap-1 bg-input rounded-md p-1 border border-border">
            {modeOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setMode(opt.value)}
                className={`flex-1 text-xs font-semibold py-2 rounded transition-all ${
                  mode === opt.value
                    ? "bg-primary text-primary-foreground shadow-[0_0_12px_hsla(217,91%,60%,0.3)]"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
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
              <span>Analyzing safety...</span>
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
              transition={{ duration: 2, ease: "linear" }}
              className="h-full bg-accent rounded-full"
            />
          </div>
        )}

        {/* Tagline */}
        <p className="text-[10px] text-muted-foreground text-center tracking-wide">
          Navigate with confidence · Well-lit areas prioritized
        </p>
      </div>
    </motion.div>
  );
};

export default RoutePanel;
