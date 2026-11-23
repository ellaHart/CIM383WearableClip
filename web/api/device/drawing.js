// GET /api/device/drawing: the clip downloads the latest drawing as raw bytes. Needs the device token.
import { getDeviceDrawing } from "../../lib/core.js";

export function GET(request) {
  return getDeviceDrawing(request);
}
