import React from "react";
import { useCurrentFrame, AbsoluteFill } from "remotion";
import { CaptionGroup } from "./types";

// Karaoke-style word-by-word caption. The active word (current frame within its
// [startFrame,endFrame]) pops and brightens; others sit dim. Positioned in the
// lower third for Shorts.
export const Captions: React.FC<{
  captions: CaptionGroup[];
  fontFamily: string;
  height: number;
}> = ({ captions, fontFamily, height }) => {
  const frame = useCurrentFrame();
  const group = captions.find((g) => frame >= g.startFrame && frame <= g.endFrame);
  if (!group) return null;

  const fontSize = Math.round(height * 0.045);
  const bottom = Math.round(height * 0.18);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: bottom,
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
          fontWeight: 800,
          fontSize,
          lineHeight: 1.15,
          textAlign: "center",
        }}
      >
        {group.words.map((w, i) => {
          const active = frame >= w.startFrame && frame <= w.endFrame;
          return (
            <span
              key={i}
              style={{
                color: active ? "#FFE55C" : "#FFFFFF",
                transform: active ? "scale(1.12)" : "scale(1)",
                display: "inline-block",
                transition: "transform 0.05s",
                textShadow:
                  "0 4px 18px rgba(0,0,0,0.9), 0 2px 4px rgba(0,0,0,0.9)",
                WebkitTextStroke: "2px rgba(0,0,0,0.55)",
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
