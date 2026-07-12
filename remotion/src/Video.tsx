import React from "react";
import { AbsoluteFill, Audio, Series, staticFile } from "remotion";
import { VideoSpec } from "./types";
import { Scene } from "./Scene";
import { Captions } from "./Captions";

// Convert a dB level (e.g. -14) to a linear volume multiplier for background music.
const dbToVolume = (db: number): number => Math.min(1, Math.max(0, Math.pow(10, db / 20)));

// Top-level composition. Scenes play back-to-back via <Series> (no overlap, so the
// per-scene audio placed inside each Scene stays in sync and the total matches
// spec.meta.durationInFrames exactly). Background music and karaoke captions layer
// on top across the whole timeline.
export const Video: React.FC<VideoSpec> = (spec) => {
  const { scenes, captions, music, render, meta } = spec;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      <Series>
        {scenes.map((scene) => (
          <Series.Sequence key={scene.index} durationInFrames={Math.max(1, scene.durationFrames)}>
            <Scene
              scene={scene}
              transitionFrames={render.transitionFrames}
              sfxEnabled={render.sfxEnabled !== false}
              sfxGainDb={render.sfxGainDb ?? -8}
            />
          </Series.Sequence>
        ))}
      </Series>

      {music ? (
        <Audio
          src={staticFile(`render/${music}`)}
          volume={dbToVolume(render.duckDb)}
          loop
        />
      ) : null}

      {render.captionsEnabled ? (
        <Captions
          captions={captions}
          fontFamily={render.captionFontFamily}
          height={meta.height}
        />
      ) : null}
    </AbsoluteFill>
  );
};
