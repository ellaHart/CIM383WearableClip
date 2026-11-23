// Local test server: serves web/public and runs the web/api functions the same way Vercel does,
// with no Vercel or Upstash account. Uses an in-memory store unless KV_REST_API_* are set.
// Usage (from web/):  npm run dev    then open http://127.0.0.1:3000
import { createServer } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = Number(process.env.PORT) || 3000;

// Load web/.env.local (KEY=value lines) without overriding real environment variables.
const envFile = join(web, ".env.local");
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (match && !(match[1] in process.env)) process.env[match[1]] = match[2];
  }
} else {
  console.warn("No web/.env.local: copy .env.example and set CONTROL_TOKEN / DEVICE_TOKEN");
}

const ROUTES = {
  "/api/catalog": "api/catalog.js",
  "/api/state": "api/state.js",
  "/api/command": "api/command.js",
  "/api/device/sync": "api/device/sync.js",
  "/api/drawing": "api/drawing.js",
  "/api/device/drawing": "api/device/drawing.js",
  "/api/spotify/login": "api/spotify/login.js",
  "/api/spotify/callback": "api/spotify/callback.js",
  "/api/spotify/disconnect": "api/spotify/disconnect.js",
};
const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".json": "application/json" };

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return chunks.length ? Buffer.concat(chunks) : undefined;
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  try {
    if (url.pathname.startsWith("/api/")) {
      const file = ROUTES[url.pathname];
      if (!file) return res.writeHead(404).end("Not found");
      const handler = (await import(pathToFileURL(join(web, file)).href))[req.method];
      if (!handler) return res.writeHead(405).end("Method not allowed");
      const body = ["GET", "HEAD"].includes(req.method) ? undefined : await readBody(req);
      const response = await handler(new Request(url, { method: req.method, headers: req.headers, body }));
      res.writeHead(response.status, Object.fromEntries(response.headers));
      res.end(Buffer.from(await response.arrayBuffer()));
      console.log(req.method, url.pathname, response.status);
      return;
    }
    const path = normalize(url.pathname === "/" ? "/index.html" : url.pathname).replace(/^(\.\.[/\\])+/, "");
    const data = await readFile(join(web, "public", path));
    res.writeHead(200, { "content-type": TYPES[extname(path)] ?? "application/octet-stream", "cache-control": "no-store" });
    res.end(data);
  } catch (err) {
    if (err.code === "ENOENT") return res.writeHead(404).end("Not found");
    console.error(err);
    res.writeHead(500).end("Server error");
  }
}).listen(PORT, "127.0.0.1", () => console.log(`Mood Clip local server: http://127.0.0.1:${PORT}`));
