"use client";

type MetricItem = {
  label: string;
  value: string | number;
  variant?: "default" | "warning" | "error";
};

type MetricsStripProps = {
  metrics: MetricItem[];
};

export function MetricsStrip({ metrics }: MetricsStripProps) {
  if (metrics.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto px-3 py-1.5">
      {metrics.map((metric) => {
        const chipClass =
          metric.variant === "error"
            ? "factory-metric-chip metric-error"
            : metric.variant === "warning"
              ? "factory-metric-chip metric-warning"
              : "factory-metric-chip";
        return (
          <span key={metric.label} className={chipClass}>
            <span className="uppercase">{metric.label}</span>
            <span className="metric-value">{metric.value}</span>
          </span>
        );
      })}
    </div>
  );
}
