import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { KenBurns, Layers as LayersType } from "./types";

// Extra overscan on the background so its parallax shift never reveals a frame
// edge. The foreground is a full-frame cutout, so a smaller overscan is enough.
const BG_OVERSCAN = 1.14;
const FG_OVERSCAN = 1.06;

// 2.5D parallax renderer: the blurred background plate and the subject cutout move
// at different rates across the scene, so a flat still gains real depth. The
// foreground travels further (and scales a touch more) than the background — that
// differential IS the parallax. Ken Burns still drives the base zoom for continuity.
export const Layers: React.FC<{
  layers: LayersType;
  kenBurns: KenBurns;
  intensity: number;
}> = ({ layers, kenBurns, intensity }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const progress = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Base Ken Burns zoom (shared), and a normalized left->right dolly for parallax.
  const zoom = interpolate(progress, [0, 1], [kenBurns.fromScale, kenBurns.toScale]);
  const dolly = interpolate(progress, [0, 1], [-1, 1]); // -1..1 across the scene
  const amt = Math.max(0, Math.min(0.6, intensity));

  // Background: heavier overscan, small shift, subtle counter-drift on Y.
  const bgScale = BG_OVERSCAN * zoom;
  const bgX = dolly * amt * 3.5;
  const bgY = kenBurns.panY * 40 * progress;

  // Foreground: moves ~2.4x further and grows slightly -> pops off the background.
  const fgScale = FG_OVERSCAN * zoom * (1 + amt * 0.06);
  const fgX = dolly * amt * 8.5;
  const fgY = -kenBurns.panY * 30 * progress;

  const cover: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    position: "absolute",
    inset: 0,
  };

  return (
    <AbsoluteFill>
      <Img
        src={staticFile(`render/${layers.bg}`)}
        style={{ ...cover, transform: `scale(${bgScale}) translate(${bgX}%, ${bgY}%)` }}
      />
      <Img
        src={staticFile(`render/${layers.fg}`)}
        style={{ ...cover, transform: `scale(${fgScale}) translate(${fgX}%, ${fgY}%)` }}
      />
    </AbsoluteFill>
  );
};
