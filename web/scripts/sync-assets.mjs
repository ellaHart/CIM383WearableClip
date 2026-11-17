// Build step (Vercel runs it as `npm run build`; the local server runs it too):
//  - copies the clip's sprite PNGs into web/public/sprites so the website uses the same art
//  - turns device/moods.json into web/lib/moods.generated.js for the API
// Both outputs are gitignored; device/moods.json and assets/sprites stay the source of truth.
import { cpSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const root = join(web, "..");

const spriteSource = join(root, "assets", "sprites");
const spriteTarget = join(web, "public", "sprites");
mkdirSync(spriteTarget, { recursive: true });
const sprites = readdirSync(spriteSource).filter((name) => name.endsWith(".png"));
for (const name of sprites) cpSync(join(spriteSource, name), join(spriteTarget, name));

const moods = JSON.parse(readFileSync(join(root, "device", "moods.json"), "utf8"));
const ids = new Set();
for (const mood of moods) {
  if (!mood.id || ids.has(mood.id)) throw new Error(`device/moods.json: missing or duplicate id "${mood.id}"`);
  if (!sprites.includes(`${mood.sprite}.png`)) throw new Error(`device/moods.json: no sprite assets/sprites/${mood.sprite}.png`);
  ids.add(mood.id);
}
writeFileSync(
  join(web, "lib", "moods.generated.js"),
  `// Generated from device/moods.json by scripts/sync-assets.mjs. Don't edit.\nexport default ${JSON.stringify(moods, null, 2)};\n`,
);

console.log(`Copied ${sprites.length} sprites and ${moods.length} moods`);
