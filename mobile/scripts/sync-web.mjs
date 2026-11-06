// Copies the shared web frontend (../frontend) into www/ so the Android app ships the same UI as desktop/web.
import { cpSync, rmSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "frontend");
const dest = join(here, "..", "www");
if (!existsSync(src)) throw new Error(`frontend not found at ${src}`);
rmSync(dest, { recursive: true, force: true });
cpSync(src, dest, { recursive: true });
console.log(`Copied ${src} -> ${dest}`);
