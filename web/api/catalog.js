// GET /api/catalog: the five modes and the moods from device/moods.json (no code needed).
import { catalog } from "../lib/core.js";

export function GET(request) {
  return catalog(request);
}
