export type KenBurns = {
  fromScale: number;
  toScale: number;
  panX: number;
  panY: number;
};

// 2.5D parallax plates: a foreground subject cutout (transparent PNG) over a
// background plate. When absent, the scene renders the flat `image` with Ken Burns.
export type Layers = {
  fg: string;
  bg: string;
};

export type Scene = {
  index: number;
  startSeconds: number;
  durationSeconds: number;
  startFrame: number;
  durationFrames: number;
  image: string | null;
  video: string | null;
  layers: Layers | null;
  audio: string | null;
  onScreenText: string;
  sfx: string;
  sfxSrc: string | null;
  kenBurns: KenBurns;
};

// Per-niche color grade -> a CSS filter stack + vignette + grain overlay.
export type Grade = {
  contrast: number;
  saturate: number;
  brightness: number;
  sepia: number;
  hueRotate: number;
  vignette: number;
  grain: number;
};

export type CaptionWord = {
  word: string;
  startFrame: number;
  endFrame: number;
  emphasis?: boolean;
};

export type CaptionGroup = {
  startFrame: number;
  endFrame: number;
  words: CaptionWord[];
};

export type VideoSpec = {
  meta: {
    kind: string;
    width: number;
    height: number;
    fps: number;
    durationInFrames: number;
    title: string;
    niche: string;
    style: string;
  };
  scenes: Scene[];
  captions: CaptionGroup[];
  music: string | null;
  render: {
    transition: string;
    transitions?: string[];
    transitionFrames: number;
    captionsEnabled: boolean;
    captionFontFamily: string;
    captionStyle?: string;
    captionPosition?: string;
    parallaxIntensity?: number;
    grade?: Grade;
    duckDb: number;
    sfxEnabled?: boolean;
    sfxGainDb?: number;
  };
};

// Default props so the composition can load in the Studio without a spec.
export const defaultSpec: VideoSpec = {
  meta: {
    kind: "short",
    width: 1080,
    height: 1920,
    fps: 30,
    durationInFrames: 90,
    title: "Preview",
    niche: "explainer",
    style: "",
  },
  scenes: [],
  captions: [],
  music: null,
  render: {
    transition: "fade",
    transitions: ["fade"],
    transitionFrames: 12,
    captionsEnabled: true,
    captionFontFamily: "Inter",
    captionStyle: "clean",
    captionPosition: "lower",
    parallaxIntensity: 0,
    grade: {
      contrast: 1.06,
      saturate: 1.08,
      brightness: 1.0,
      sepia: 0.0,
      hueRotate: 0,
      vignette: 0.28,
      grain: 0.05,
    },
    duckDb: -14,
    sfxEnabled: true,
    sfxGainDb: -8,
  },
};
