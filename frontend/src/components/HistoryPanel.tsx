import { timeAgo } from "../history";
import { IconClock } from "../icons";
import type { History } from "../types";
import { Section } from "../ui";

/** Every edit step for this photo, newest first. Click a step to return to it. */
export function HistoryPanel({ history, onJump }: { history: History | null; onJump: (index: number) => void }) {
  if (!history) return null;
  const items = history.entries.map((e, i) => ({ ...e, i })).reverse();
  return (
    <Section id="history" title="History" icon={<IconClock size={16} />} defaultOpen={false}
      right={<span className="muted mono">{history.index + 1}/{history.entries.length}</span>}>
      <ol className="history-list" aria-label="Edit history">
        {items.map((e) => (
          <li key={e.i}>
            <button className={`history-item ${e.i === history.index ? "current" : ""} ${e.i > history.index ? "undone" : ""}`}
              aria-current={e.i === history.index ? "step" : undefined} onClick={() => onJump(e.i)} title="Go back to this step">
              <span className="h-dot" aria-hidden="true" />
              <span className="h-label">{e.label}</span>
              <span className="h-time">{e.i === history.index ? "now" : e.i > history.index ? "undone" : timeAgo(e.time)}</span>
            </button>
          </li>
        ))}
      </ol>
    </Section>
  );
}
