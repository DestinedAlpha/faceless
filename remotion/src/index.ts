// Remotion entry point. `npx remotion render src/index.ts Faceless <out>` loads
// this, which registers the root composition tree.
import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);
