// POST /api/spotify/disconnect: deletes the stored Spotify tokens. Needs the control code.
import { postSpotifyDisconnect } from "../../lib/core.js";

export function POST(request) {
  return postSpotifyDisconnect(request);
}
