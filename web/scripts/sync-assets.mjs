// Copies the clip's sprite PNGs into web/public/sprites so the website uses the same art.
// Runs automatically before `npm run dev` and `npm run deploy`.
import { cpSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = join(root, "assets", "sprites");
const target = join(root, "web", "public", "sprites");

mkdirSync(target, { recursive: true });
const files = readdirSync(source).filter((name) => name.endsWith(".png"));
for (const name of files) cpSync(join(source, name), join(target, name));
console.log(`Copied ${files.length} sprites to web/public/sprites`);
