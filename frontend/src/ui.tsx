import { useState, type ReactNode } from "react";
import { IconChevron, IconInfo } from "./icons";

/** Small (i) with an accessible tooltip, replacing long explanatory text. */
export function InfoTip({ text }: { text: string }) {
  return (
    <span className="infotip" tabIndex={0} role="note" aria-label={text}>
      <IconInfo size={14} />
      <span className="infotip-bubble" role="tooltip">{text}</span>
    </span>
  );
}

/** Collapsible side-panel section. Open state is remembered per section. */
export function Section({ id, title, icon, right, children, defaultOpen = true }: {
  id: string; title: string; icon?: ReactNode; right?: ReactNode; children: ReactNode; defaultOpen?: boolean;
}) {
  const key = `bpe.section.${id}`;
  const [open, setOpen] = useState<boolean>(() => {
    try { const v = localStorage.getItem(key); return v === null ? defaultOpen : v === "1"; } catch { return defaultOpen; }
  });
  const toggle = () => {
    setOpen((o) => { try { localStorage.setItem(key, o ? "0" : "1"); } catch { /* ignore */ } return !o; });
  };
  return (
    <section className={`panel-section ${open ? "open" : ""}`}>
      <div className="section-head">
        <button className="section-toggle" aria-expanded={open} onClick={toggle}>
          <IconChevron size={14} className="chev" />
          {icon && <span className="section-icon">{icon}</span>}
          <span className="section-title">{title}</span>
        </button>
        {right && <div className="section-right">{right}</div>}
      </div>
      {open && <div className="section-body">{children}</div>}
    </section>
  );
}

export interface SliderDef { key: string; label: string; min: number; max: number; step: number; unit?: string; hint?: string }

/** Refined slider: label + value, track filled from the centre for two-way
 * controls, double-click or the reset icon returns to the Auto Edit value. */
export function Slider({ def, value, disabled, onChange, resetTo }: {
  def: SliderDef; value: number; disabled?: boolean; onChange: (v: number) => void; resetTo?: number;
}) {
  const id = `sl-${def.key}`;
  const target = resetTo ?? 0;
  const shown = def.step < 1 ? value.toFixed(def.step < 0.1 ? 2 : 1) : String(Math.round(value));
  const span = def.max - def.min;
  const pos = ((value - def.min) / span) * 100;
  const origin = def.min < 0 ? ((0 - def.min) / span) * 100 : 0;
  const a = Math.min(pos, origin), b = Math.max(pos, origin);
  const track = `linear-gradient(to right, var(--track) 0%, var(--track) ${a}%, var(--accent) ${a}%, var(--accent) ${b}%, var(--track) ${b}%, var(--track) 100%)`;
  const changed = Math.abs(value - target) > 1e-9;
  return (
    <div className={`slider ${disabled ? "is-disabled" : ""}`}>
      <div className="slider-head">
        <label htmlFor={id}>{def.label}{def.hint && <InfoTip text={def.hint} />}</label>
        <span className="slider-value">
          <button className={`reset-btn ${changed ? "visible" : ""}`} disabled={disabled || !changed}
            onClick={() => onChange(target)} aria-label={`Reset ${def.label}`}
            title={resetTo !== undefined ? "Back to the Auto Edit value" : "Back to zero"}>↺</button>
          <output htmlFor={id}>{value > 0 && def.min < 0 ? "+" : ""}{shown}{def.unit ?? ""}</output>
        </span>
      </div>
      <input id={id} type="range" min={def.min} max={def.max} step={def.step} value={value}
        disabled={disabled} style={{ background: track }}
        onChange={(e) => onChange(Number(e.target.value))} onDoubleClick={() => onChange(target)} />
    </div>
  );
}

export function IconButton({ label, children, active, ...rest }: {
  label: string; children: ReactNode; active?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={`icon-btn ${active ? "active" : ""}`} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  );
}
