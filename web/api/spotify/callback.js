// GET /api/spotify/callback: Spotify sends the browser back here after sign-in (checked by state).
import { getSpotifyCallback } from "../../lib/core.js";

export function GET(request) {
  return getSpotifyCallback(request);
}
