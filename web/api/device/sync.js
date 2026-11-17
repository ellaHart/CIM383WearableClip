// POST /api/device/sync: the clip reports what it shows and gets the latest command. Needs the device token.
import { postDeviceSync } from "../../lib/core.js";

export function POST(request) {
  return postDeviceSync(request);
}
