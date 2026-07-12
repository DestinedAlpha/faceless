import React from "react";
import { Composition } from "remotion";
import { Video } from "./Video";
import { VideoSpec, defaultSpec } from "./types";

// A single composition drives both Shorts (9:16) and long-form (16:9). The Python
// bridge passes the whole video_spec.json as inputProps (--props), and
// calculateMetadata pulls dimensions/fps/duration straight off spec.meta so one
// composition adapts to whatever the selector chose. defaultSpec keeps the Studio
// loadable with no props.
export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Faceless"
      component={Video}
      durationInFrames={defaultSpec.meta.durationInFrames}
      fps={defaultSpec.meta.fps}
      width={defaultSpec.meta.width}
      height={defaultSpec.meta.height}
      defaultProps={defaultSpec as unknown as VideoSpec}
      calculateMetadata={({ props }) => {
        const m = (props as unknown as VideoSpec).meta;
        return {
          durationInFrames: Math.max(1, Math.round(m.durationInFrames)),
          fps: m.fps,
          width: m.width,
          height: m.height,
        };
      }}
    />
  );
};
