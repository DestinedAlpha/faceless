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
import { Layers } from "./Layers";
import { entrance, TransitionType } from "./Transitions";

// A slight overscan so Ken Burns pan/zoom never reveals the background edge even
// when a scene's zoom bottoms out at scale 1.0.
const OVERSCAN = 1.06;

// dB -> linear volume multiplier.
const dbToVolume = (db: number): number =>
  Math.min(1, Math.max(0, Math.pow(10, db / 20)));

// One scene: a full-bleed visual — 2.5D parallax layers when available, else a
// stock clip or a flat AI still under a Ken Burns move — plus a per-cut entrance
// transition, an optional big on-screen title, the scene's own narration audio,
// and (Phase 1) a one-shot sound effect at the scene's start for punch.
export const Scene: React.FC<{
  scene: SceneType;
  transitionFrames: number;
  transitionType?: TransitionType;
  parallaxIntensity?: number;
  sfxEnabled?: boolean;
  sfxGainDb?: number;
}> = ({
  scene,
  transitionFrames,
  transitionType = "fade",
  parallaxIntensity = 0,
  sfxEnabled = true,
  sfxGainDb = -8,
}) => {
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

  // Per-cut entrance (fade/slide/whip/zoom/flash), timed to this scene's start.
  const enter = entrance(transitionType, frame, transitionFrames, scene.index);

  const transform = `scale(${scale}) translate(${panX}%, ${panY}%)`;
  const cover: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform,
  };

  const useParallax = scene.layers && parallaxIntensity > 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      {/* Visual layer carries the entrance opacity + transform. */}
      <AbsoluteFill style={{ opacity: enter.opacity, transform: enter.transform }}>
        {useParallax ? (
          <Layers layers={scene.layers!} kenBurns={kb} intensity={parallaxIntensity} />
        ) : scene.video ? (
          <OffthreadVideo src={staticFile(`render/${scene.video}`)} style={cover} muted />
        ) : scene.image ? (
          <Img src={staticFile(`render/${scene.image}`)} style={cover} />
        ) : null}
      </AbsoluteFill>

      {/* White flash for the "flash" cut (decays over the entrance window). */}
      {enter.flash > 0 ? (
        <AbsoluteFill style={{ backgroundColor: "#FFFFFF", opacity: enter.flash }} />
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
