// POST /api/spotify/login: returns Spotify's sign-in URL (with a one-time state). Needs the control code.
import { postSpotifyLogin } from "../../lib/core.js";

export function POST(request) {
  return postSpotifyLogin(request);
}
