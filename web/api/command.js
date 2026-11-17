// POST /api/command: { "mode": "moods", "mood": "love" }. Needs the control code.
import { postCommand } from "../lib/core.js";

export function POST(request) {
  return postCommand(request);
}
