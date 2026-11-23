import { timeAgo } from "../history";
import type { History } from "../types";

interface Props {
  history: History | null;
  onJump: (index: number) => void;
}

/** Every edit step for this photo, newest at the top. Clicking a step
 * returns the photo to exactly that state (and it can be redone). Saved with
 * the project, so it survives closing the app. */
export function HistoryPanel({ history, onJump }: Props) {
  if (!history) return null;
  const items = history.entries.map((e, i) => ({ ...e, i })).reverse();
  return (
    <section className="history-panel" aria-label="Edit history">
      <h3>History</h3>
      <ol className="history-list">
        {items.map((e) => (
          <li key={e.i}>
            <button className={`history-item ${e.i === history.index ? "current" : ""} ${e.i > history.index ? "undone" : ""}`}
              aria-current={e.i === history.index ? "step" : undefined}
              onClick={() => onJump(e.i)} title="Go back to this step">
              <span className="h-label">{e.label}</span>
              <span className="h-time">{e.i === history.index ? "current" : e.i > history.index ? "undone" : timeAgo(e.time)}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="small muted">Click any step to go back to it. Undone steps stay greyed out until you make a new edit.</p>
    </section>
  );
}
