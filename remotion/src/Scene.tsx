import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Scene as SceneType } from "./types";

// A slight overscan so Ken Burns pan/zoom never reveals the background edge even
// when a scene's zoom bottoms out at scale 1.0.
const OVERSCAN = 1.06;

// dB -> linear volume multiplier.
const dbToVolume = (db: number): number =>
  Math.min(1, Math.max(0, Math.pow(10, db / 20)));

// One scene: a full-bleed AI still (or stock clip) under a Ken Burns move, a short
// fade-in for a soft cut, an optional big on-screen title, the scene's own narration
// audio, and (Phase 1) a one-shot sound effect at the scene's start for punch.
export const Scene: React.FC<{
  scene: SceneType;
  transitionFrames: number;
  sfxEnabled?: boolean;
  sfxGainDb?: number;
}> = ({ scene, transitionFrames, sfxEnabled = true, sfxGainDb = -8 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const kb = scene.kenBurns;

  const progress = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = OVERSCAN * interpolate(progress, [0, 1], [kb.fromScale, kb.toScale]);
  const panX = interpolate(progress, [0, 1], [0, kb.panX * 100]);
  const panY = interpolate(progress, [0, 1], [0, kb.panY * 100]);

  const fadeIn = interpolate(frame, [0, Math.max(1, transitionFrames)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const transform = `scale(${scale}) translate(${panX}%, ${panY}%)`;
  const cover: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform,
  };

  return (
    <AbsoluteFill style={{ opacity: fadeIn, backgroundColor: "#000000" }}>
      {scene.video ? (
        <OffthreadVideo src={staticFile(`render/${scene.video}`)} style={cover} muted />
      ) : scene.image ? (
        <Img src={staticFile(`render/${scene.image}`)} style={cover} />
      ) : null}

      {scene.onScreenText ? (
        <AbsoluteFill
          style={{
            justifyContent: "flex-start",
            alignItems: "center",
            paddingTop: "12%",
            paddingLeft: 60,
            paddingRight: 60,
          }}
        >
          <div
            style={{
              color: "#FFFFFF",
              fontFamily: "Inter, system-ui, sans-serif",
              fontWeight: 900,
              fontSize: "min(7vw, 84px)",
              lineHeight: 1.1,
              textAlign: "center",
              textShadow: "0 6px 24px rgba(0,0,0,0.85)",
              WebkitTextStroke: "2px rgba(0,0,0,0.5)",
            }}
          >
            {scene.onScreenText}
          </div>
        </AbsoluteFill>
      ) : null}

      {scene.audio ? <Audio src={staticFile(`render/${scene.audio}`)} /> : null}

      {sfxEnabled && scene.sfxSrc ? (
        <Audio src={staticFile(`render/${scene.sfxSrc}`)} volume={dbToVolume(sfxGainDb)} />
      ) : null}
    </AbsoluteFill>
  );
};
