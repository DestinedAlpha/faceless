import { interpolate, Easing } from "remotion";

// Entrance-transition library. Rather than cross-dissolving overlapping scenes
// (which would desync the per-scene audio that drives this timeline), each scene
// plays a short entrance move over its first `frames` frames. Cuts still feel
// varied and "produced" — a whip-in, a zoom-punch, a slide — and land exactly on
// the scene boundary, while audio and captions stay frame-accurate.
export type TransitionType = "fade" | "slide" | "whip" | "zoom" | "flash" | "none";

export type Entrance = {
  opacity: number;
  transform: string;
  // 0..1 white flash strength for the "flash" cut (rendered as an overlay).
  flash: number;
};

const EASE = Easing.out(Easing.cubic);

// Normalized 0..1 eased progress across the entrance window.
const prog = (frame: number, frames: number): number =>
  interpolate(frame, [0, Math.max(1, frames)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });

// Compute the entrance transform/opacity for a scene. `index` alternates the
// travel direction so consecutive slide/whip cuts don't all come from one side.
export const entrance = (
  type: TransitionType,
  frame: number,
  frames: number,
  index: number
): Entrance => {
  const t = prog(frame, frames);
  const dir = index % 2 === 0 ? 1 : -1;

  switch (type) {
    case "none":
      return { opacity: 1, transform: "none", flash: 0 };

    case "slide": {
      const x = interpolate(t, [0, 1], [dir * 45, 0]);
      return { opacity: t, transform: `translateX(${x}%)`, flash: 0 };
    }

    case "whip": {
      // Fast horizontal whip-in from further out; snaps to place.
      const x = interpolate(t, [0, 1], [dir * 90, 0]);
      return { opacity: Math.min(1, t * 1.6), transform: `translateX(${x}%)`, flash: 0 };
    }

    case "zoom": {
      // Zoom-punch: starts slightly overscaled and settles in.
      const s = interpolate(t, [0, 1], [1.18, 1]);
      return { opacity: t, transform: `scale(${s})`, flash: 0 };
    }

    case "flash": {
      // Hard cut with a quick white flash that decays over the window.
      return { opacity: 1, transform: "none", flash: 1 - t };
    }

    case "fade":
    default:
      return { opacity: t, transform: "none", flash: 0 };
  }
};
