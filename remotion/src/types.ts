export type KenBurns = {
  fromScale: number;
  toScale: number;
  panX: number;
  panY: number;
};

export type Scene = {
  index: number;
  startSeconds: number;
  durationSeconds: number;
  startFrame: number;
  durationFrames: number;
  image: string | null;
  video: string | null;
  audio: string | null;
  onScreenText: string;
  sfx: string;
  sfxSrc: string | null;
  kenBurns: KenBurns;
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
    transitionFrames: number;
    captionsEnabled: boolean;
    captionFontFamily: string;
    captionStyle?: string;
    captionPosition?: string;
    parallaxIntensity?: number;
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
    transitionFrames: 12,
    captionsEnabled: true,
    captionFontFamily: "Inter",
    captionStyle: "clean",
    captionPosition: "lower",
    parallaxIntensity: 0,
    duckDb: -14,
    sfxEnabled: true,
    sfxGainDb: -8,
  },
};
