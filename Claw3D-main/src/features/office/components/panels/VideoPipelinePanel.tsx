"use client";

export type PipelineAgentStatus = "idle" | "working" | "complete" | "error";

type PipelineAgentState = {
  name: string;
  role: string;
  status: PipelineAgentStatus;
  statusLine: string;
  detail?: string;
};

type VideoPipelinePanelProps = {
  agents: PipelineAgentState[];
  pipelineActive: boolean;
  lastVideoUrl?: string | null;
  totalVideos: number;
  totalViews: number;
  onStartPipeline?: () => void;
};

const STATUS_LED_CLASS: Record<PipelineAgentStatus, string> = {
  idle: "factory-status-led led-idle",
  working: "factory-status-led led-active factory-pulse",
  complete: "factory-status-led led-active",
  error: "factory-status-led led-error",
};

const STATUS_LABEL: Record<PipelineAgentStatus, string> = {
  idle: "IDLE",
  working: "WORKING",
  complete: "DONE",
  error: "ERROR",
};

export function VideoPipelinePanel({
  agents,
  pipelineActive,
  lastVideoUrl,
  totalVideos,
  totalViews,
  onStartPipeline,
}: VideoPipelinePanelProps) {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4 ui-scroll">
      {/* Pipeline header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.32em] text-cyan-300/80">
            Video Pipeline
          </div>
          <div className="mt-0.5 font-mono text-[11px] text-white/45">
            Research → Generate → Publish
          </div>
        </div>
        {onStartPipeline ? (
          <button
            type="button"
            onClick={onStartPipeline}
            disabled={pipelineActive}
            className="rounded border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-cyan-200 transition-colors hover:border-cyan-400/40 hover:text-cyan-100 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {pipelineActive ? "Running…" : "Start Pipeline"}
          </button>
        ) : null}
      </div>

      {/* Agent status cards */}
      <div className="flex flex-col gap-2">
        {agents.map((agent) => (
          <div
            key={agent.name}
            className="factory-panel px-3 py-2.5"
          >
            <div className="flex items-center gap-2">
              <span className={STATUS_LED_CLASS[agent.status]} />
              <span className="font-mono text-[11px] font-semibold text-white/90">
                {agent.name}
              </span>
              <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-white/40">
                {agent.role}
              </span>
              <span className="ml-auto font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-300/60">
                {STATUS_LABEL[agent.status]}
              </span>
            </div>
            <div className="mt-1.5 font-mono text-[10px] text-white/55 leading-relaxed">
              {agent.statusLine}
            </div>
            {agent.detail ? (
              <div className="mt-1 font-mono text-[9px] text-cyan-300/40 leading-relaxed">
                {agent.detail}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {/* Pipeline stats */}
      <div className="factory-panel px-3 py-2.5">
        <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.24em] text-cyan-300/60 mb-2">
          Pipeline Stats
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/40">
              Videos
            </div>
            <div className="font-mono text-[13px] font-semibold text-cyan-300">
              {totalVideos}
            </div>
          </div>
          <div>
            <div className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/40">
              Total Views
            </div>
            <div className="font-mono text-[13px] font-semibold text-cyan-300">
              {totalViews.toLocaleString()}
            </div>
          </div>
        </div>
      </div>

      {/* Last published video */}
      {lastVideoUrl ? (
        <div className="factory-panel px-3 py-2.5">
          <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.24em] text-cyan-300/60 mb-1">
            Last Published
          </div>
          <a
            href={lastVideoUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="block truncate font-mono text-[10px] text-cyan-300/80 underline decoration-cyan-500/30 hover:text-cyan-100"
          >
            {lastVideoUrl}
          </a>
        </div>
      ) : null}
    </div>
  );
}
