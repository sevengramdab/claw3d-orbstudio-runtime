"use client";

type StatBar = {
  label: string;
  value: number;
  max: number;
  variant?: "default" | "warning" | "error";
  suffix?: string;
};

type ProductionStatsPanelProps = {
  stats: StatBar[];
};

export function ProductionStatsPanel({ stats }: ProductionStatsPanelProps) {
  if (stats.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.24em] text-cyan-300/60">
        Production
      </div>
      {stats.map((stat) => {
        const pct = stat.max > 0 ? Math.min(100, (stat.value / stat.max) * 100) : 0;
        const barClass =
          stat.variant === "error"
            ? "factory-bar-fill bar-error"
            : stat.variant === "warning"
              ? "factory-bar-fill bar-warning"
              : "factory-bar-fill";
        return (
          <div key={stat.label}>
            <div className="flex items-center justify-between mb-0.5">
              <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-white/50">
                {stat.label}
              </span>
              <span className="font-mono text-[10px] font-semibold text-cyan-300/80">
                {stat.value}{stat.suffix || ""}
                {stat.max < Infinity ? ` / ${stat.max}${stat.suffix || ""}` : ""}
              </span>
            </div>
            <div className="h-1 w-full rounded-full bg-white/5">
              <div
                className={barClass}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
