import React from "react";
import { AbsoluteFill } from "remotion";
import { Grade as GradeType } from "./types";

// A tiny tiled SVG noise field, used as a film-grain overlay at low opacity. Static
// (frame-independent) so it stays cheap and doesn't shimmer distractingly.
const GRAIN_URI =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>` +
      `<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/>` +
      `<feColorMatrix type='saturate' values='0'/></filter>` +
      `<rect width='100%' height='100%' filter='url(#n)'/></svg>`
  );

// Wraps the whole composition in the niche's signature look: a CSS filter stack
// (contrast/saturate/brightness/sepia/hue) over the visuals, a corner vignette,
// and a subtle film-grain layer. All free and GPU-free. Captions/titles render
// ABOVE this so text stays crisp and un-graded.
export const Grade: React.FC<{ grade?: GradeType; children: React.ReactNode }> = ({
  grade,
  children,
}) => {
  if (!grade) return <>{children}</>;

  const filter =
    `contrast(${grade.contrast}) saturate(${grade.saturate}) ` +
    `brightness(${grade.brightness}) sepia(${grade.sepia}) ` +
    `hue-rotate(${grade.hueRotate}deg)`;

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ filter }}>{children}</AbsoluteFill>

      {grade.vignette > 0 ? (
        <AbsoluteFill
          style={{
            boxShadow: `inset 0 0 ${Math.round(grade.vignette * 500)}px ${Math.round(
              grade.vignette * 260
            )}px rgba(0,0,0,${Math.min(0.9, grade.vignette).toFixed(3)})`,
            pointerEvents: "none",
          }}
        />
      ) : null}

      {grade.grain > 0 ? (
        <AbsoluteFill
          style={{
            backgroundImage: `url("${GRAIN_URI}")`,
            backgroundRepeat: "repeat",
            opacity: grade.grain,
            mixBlendMode: "overlay",
            pointerEvents: "none",
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};
