import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
// Public dir holds the per-run staged assets (images/audio/music).
Config.setPublicDir("public");
