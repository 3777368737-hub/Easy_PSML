import type { CSSProperties } from "react";
export type IconName =
  | "compass"
  | "home"
  | "user"
  | "target"
  | "chat"
  | "file"
  | "spark"
  | "check"
  | "upload"
  | "book"
  | "menu"
  | "close"
  | "arrow-right"
  | "plus"
  | "layers"
  | "clock"
  | "folder"
  | "volume"
  | "volume-off";
const paths: Record<IconName, string> = {
  compass:
    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z M16 8l-2.5 5.5L8 16l2.5-5.5L16 8Z",
  home: "m3 10 9-7 9 7 M5 9v11h14V9 M9 20v-7h6v7",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z M4 21v-2a8 8 0 0 1 16 0v2",
  target: "M21 12a9 9 0 1 1-9-9 M17 12a5 5 0 1 1-5-5 M12 12l9-9 M16 3h5v5",
  chat: "M21 11a8 8 0 0 1-8 8H8l-5 3V11a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8Z M7 10h10 M7 14h6",
  file: "M14 2H5v20h14V7l-5-5Z M14 2v6h5 M8 12h8 M8 16h6",
  spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z",
  check: "m5 12 4 4L19 6",
  upload: "M12 16V3 M7 8l5-5 5 5 M4 16v5h16v-5",
  book: "M12 5v16 M3 3l9 2 9-2v16l-9 2-9-2V3Z",
  menu: "M4 7h16 M4 12h16 M4 17h16",
  close: "M6 6l12 12 M18 6 6 18",
  "arrow-right": "M5 12h14 M13 6l6 6-6 6",
  plus: "M12 5v14 M5 12h14",
  layers: "m12 3 9 5-9 5-9-5 9-5Z M3 12l9 5 9-5 M3 16l9 5 9-5",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z M12 7v5l3 2",
  folder: "M3 6h7l2 2h9v11H3V6Z",
  volume: "M11 5 6 9H3v6h3l5 4V5Z M15 9a4 4 0 0 1 0 6 M18 6a8 8 0 0 1 0 12",
  "volume-off": "M11 5 6 9H3v6h3l5 4V5Z M16 9l5 6 M21 9l-5 6",
};
export default function Icon({
  name,
  size = 20,
  style,
}: {
  name: IconName;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  );
}
