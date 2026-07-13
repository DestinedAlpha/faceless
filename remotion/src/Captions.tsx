import React from "react";
import { useCurrentFrame, useVideoConfig, AbsoluteFill, spring, interpolate } from "remotion";
import { CaptionGroup } from "./types";

// Per-niche caption looks. Font size is expressed as a fraction of frame height so
// it scales across formats. `pop` toggles the springy bounce-in (brainrot energy).
type Preset = {
  baseColor: string;
  activeColor: string;
  emphasisColor: string;
  weight: number;
  sizeFrac: number;
  uppercase: boolean;
  stroke: string;
  pop: boolean;
};

const PRESETS: Record<string, Preset> = {
  clean: {
    baseColor: "#FFFFFF",
    activeColor: "#FFE55C",
    emphasisColor: "#FFD23F",
    weight: 800,
    sizeFrac: 0.044,
    uppercase: false,
    stroke: "2px rgba(0,0,0,0.55)",
    pop: false,
  },
  bold: {
    baseColor: "#FFFFFF",
    activeColor: "#4FD1FF",
    emphasisColor: "#33C4FF",
    weight: 900,
    sizeFrac: 0.05,
    uppercase: true,
    stroke: "3px rgba(0,0,0,0.6)",
    pop: false,
  },
  brainrot: {
    baseColor: "#FFFFFF",
    activeColor: "#7CFF4F",
    emphasisColor: "#B4FF3A",
    weight: 900,
    sizeFrac: 0.058,
    uppercase: true,
    stroke: "4px rgba(0,0,0,0.7)",
    pop: true,
  },
};

// Karaoke-style word-by-word caption. Each word pops on (spring) as it is spoken;
// the active word brightens and scales; the emphasis word of a group is larger and
// carries the accent color even before it's active so the eye lands on the key word.
export const Captions: React.FC<{
  captions: CaptionGroup[];
  fontFamily: string;
  height: number;
  style?: string;
  position?: string;
}> = ({ captions, fontFamily, height, style, position }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const group = captions.find((g) => frame >= g.startFrame && frame <= g.endFrame);
  if (!group) return null;

  const preset = PRESETS[style || "clean"] || PRESETS.clean;
  const fontSize = Math.round(height * preset.sizeFrac);
  const centered = position === "center";

  return (
    <AbsoluteFill
      style={{
        justifyContent: centered ? "center" : "flex-end",
        alignItems: "center",
        paddingBottom: centered ? 0 : Math.round(height * 0.18),
        paddingLeft: 60,
        paddingRight: 60,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.35em",
          justifyContent: "center",
          fontFamily: `${fontFamily}, system-ui, sans-serif`,
          fontWeight: preset.weight,
          fontSize,
          lineHeight: 1.15,
          textAlign: "center",
          textTransform: preset.uppercase ? "uppercase" : "none",
        }}
      >
        {group.words.map((w, i) => {
          const active = frame >= w.startFrame && frame <= w.endFrame;
          const emph = !!w.emphasis;

          // Pop-on when the word is first spoken (spring settles to 1).
          const appear = spring({
            frame: frame - w.startFrame,
            fps,
            config: preset.pop
              ? { damping: 9, stiffness: 170, mass: 0.6 }
              : { damping: 200 },
            durationInFrames: preset.pop ? 14 : 8,
          });
          const appearScale = interpolate(appear, [0, 1], [preset.pop ? 0.6 : 0.9, 1]);

          const activeScale = active ? (emph ? 1.22 : 1.12) : emph ? 1.06 : 1;
          const color = emph
            ? preset.emphasisColor
            : active
            ? preset.activeColor
            : preset.baseColor;

          return (
            <span
              key={i}
              style={{
                color,
                display: "inline-block",
                transform: `scale(${(appearScale * activeScale).toFixed(3)})`,
                fontSize: emph ? "1.12em" : "1em",
                textShadow: "0 4px 18px rgba(0,0,0,0.9), 0 2px 4px rgba(0,0,0,0.9)",
                WebkitTextStroke: preset.stroke,
              }}
            >
              {w.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
