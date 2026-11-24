/** Small inline icon set (24x24, stroke = currentColor). No external assets. */
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
const base = (size = 18): SVGProps<SVGSVGElement> => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.75, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true,
});
const mk = (paths: JSX.Element) => ({ size, ...rest }: P) => <svg {...base(size)} {...rest}>{paths}</svg>;

export const IconImport = mk(<><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" /></>);
export const IconExport = mk(<><path d="M12 15V3" /><path d="m7 8 5-5 5 5" /><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" /></>);
export const IconWand = mk(<><path d="m3 21 12-12" /><path d="M15 3v2M19 7h2M18 4l1.5-1.5M13 7H11M18 10l1.5 1.5" /><path d="m14 8 2 2" /></>);
export const IconStack = mk(<><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 13 9 5 9-5" /></>);
export const IconUndo = mk(<><path d="M9 14 4 9l5-5" /><path d="M4 9h11a5 5 0 0 1 0 10h-3" /></>);
export const IconRedo = mk(<><path d="m15 14 5-5-5-5" /><path d="M20 9H9a5 5 0 0 0 0 10h3" /></>);
export const IconRevert = mk(<><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></>);
export const IconImage = mk(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m3 16 5-5 4 4 3-3 6 6" /><circle cx="15.5" cy="8.5" r="1.5" /></>);
export const IconBefore = mk(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 15h10" strokeDasharray="2 2" /></>);
export const IconSplit = mk(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M12 2v20" /><path d="m9 10-2 2 2 2M15 10l2 2-2 2" /></>);
export const IconSide = mk(<><rect x="3" y="4" width="8" height="16" rx="1.5" /><rect x="13" y="4" width="8" height="16" rx="1.5" /></>);
export const IconFit = mk(<><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></>);
export const IconZoom = mk(<><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /><path d="M11 8v6M8 11h6" /></>);
export const IconCopy = mk(<><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>);
export const IconPaste = mk(<><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V3h6v1" /><path d="M9 11h6M9 15h4" /></>);
export const IconCrop = mk(<><path d="M6 2v14a2 2 0 0 0 2 2h14" /><path d="M2 6h14a2 2 0 0 1 2 2v14" /></>);
export const IconBird = mk(<><path d="M16 7h.01" /><path d="M3.5 18A9.5 9.5 0 0 1 13 8.5h.5a4.5 4.5 0 0 1 4.5 4.5c0 4-3 7-8 7H3.5Z" /><path d="M18 9l3-1-3-1" /><path d="M7 20l1.5-4" /></>);
export const IconClock = mk(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>);
export const IconInfo = mk(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>);
export const IconCamera = mk(<><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z" /><circle cx="12" cy="13" r="3.5" /></>);
export const IconSun = mk(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>);
export const IconPalette = mk(<><path d="M12 3a9 9 0 0 0 0 18c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.4A4.6 4.6 0 0 0 22 9.8C22 6 17.5 3 12 3Z" /><circle cx="7.5" cy="11" r="1" /><circle cx="10" cy="7" r="1" /><circle cx="15" cy="7" r="1" /></>);
export const IconSparkle = mk(<><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" /><path d="M19 17l.7 1.8 1.8.7-1.8.7L19 22l-.7-1.8-1.8-.7 1.8-.7Z" /></>);
export const IconChevron = mk(<path d="m9 6 6 6-6 6" />);
export const IconX = mk(<path d="M6 6l12 12M18 6 6 18" />);
export const IconFolder = mk(<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />);
export const IconCheck = mk(<path d="m5 12 5 5L20 7" />);
export const IconAlert = mk(<><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17h.01" /></>);
export const IconPanel = mk(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></>);
export const IconSettings = mk(<><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></>);
