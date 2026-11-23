// POST /api/drawing: upload a 320x170 1-bit drawing (raw 6800-byte body). Needs the control code.
// GET  /api/drawing: the latest drawing as raw bytes. Needs the control code.
import { getDrawing, postDrawing } from "../lib/core.js";

export function GET(request) {
  return getDrawing(request);
}

export function POST(request) {
  return postDrawing(request);
}
