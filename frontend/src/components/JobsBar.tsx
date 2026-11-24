import { api } from "../api";
import type { Job } from "../types";

export function JobsBar({ jobs }: { jobs: Job[] }) {
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  if (!active.length) return null;
  return (
    <div className="jobs-bar" role="status" aria-live="polite">
      {active.map((j) => (
        <div key={j.id} className="job">
          <span className="job-text">{j.title}: {j.done} of {j.total}{j.message ? ` (${j.message})` : ""}</span>
          <progress max={j.total} value={j.done + j.item_progress} />
          <button className="btn small ghost" onClick={() => api.cancelJob(j.id)} aria-label={`Cancel ${j.title}`}>Cancel</button>
        </div>
      ))}
    </div>
  );
}
