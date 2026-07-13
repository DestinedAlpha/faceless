import React from "react";
import { AbsoluteFill, Audio, Series, staticFile } from "remotion";
import { VideoSpec } from "./types";
import { Scene } from "./Scene";
import { Captions } from "./Captions";
import { Grade } from "./Grade";
import { TransitionType } from "./Transitions";

// Convert a dB level (e.g. -14) to a linear volume multiplier for background music.
const dbToVolume = (db: number): number => Math.min(1, Math.max(0, Math.pow(10, db / 20)));

// Top-level composition. Scenes play back-to-back via <Series> (no overlap, so the
// per-scene audio placed inside each Scene stays in sync and the total matches
// spec.meta.durationInFrames exactly). Each scene gets a per-cut entrance transition
// (cycled from the playbook's transition set) and, when parallax plates exist, 2.5D
// depth. The whole visual stack is wrapped in the niche's color grade; music and
// karaoke captions layer on top (captions above the grade so text stays crisp).
export const Video: React.FC<VideoSpec> = (spec) => {
  const { scenes, captions, music, render, meta } = spec;

  const transitions: TransitionType[] =
    (render.transitions && render.transitions.length
      ? render.transitions
      : [render.transition || "fade"]) as TransitionType[];

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      <Grade grade={render.grade}>
        <Series>
          {scenes.map((scene, i) => (
            <Series.Sequence key={scene.index} durationInFrames={Math.max(1, scene.durationFrames)}>
              <Scene
                scene={scene}
                transitionFrames={render.transitionFrames}
                transitionType={i === 0 ? "fade" : transitions[i % transitions.length]}
                parallaxIntensity={render.parallaxIntensity ?? 0}
                sfxEnabled={render.sfxEnabled !== false}
                sfxGainDb={render.sfxGainDb ?? -8}
              />
            </Series.Sequence>
          ))}
        </Series>
      </Grade>

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
          style={render.captionStyle}
          position={render.captionPosition}
        />
      ) : null}
    </AbsoluteFill>
  );
};
