// GET /api/state: { desired, reported }. Needs the control code.
import { getState } from "../lib/core.js";

export function GET(request) {
  return getState(request);
}
