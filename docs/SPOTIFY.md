# Spotify Now Playing: setup

The clip's Spotify screen shows the song you're playing (title, artist, playing/paused). It is
display-only: nothing on the clip or the website controls playback.

## What Spotify requires (checked November 2026)
- **Spotify Premium on the account that owns the developer app.** Since February/March 2026, every
  Development Mode app stops working if its owner doesn't have active Premium.
- **Development Mode is enough.** It allows up to 5 users; you only need yourself. (Extended quota
  is now only for registered businesses.)
- Endpoint: `GET /v1/me/player/currently-playing` (still available after the February 2026 changes).
- Scope: only `user-read-currently-playing`.
- Redirect URIs must be HTTPS (or a loopback IP); `localhost` isn't accepted.

## 1. Create the Spotify app
1. Go to <https://developer.spotify.com/dashboard> and log in with the **Premium** account.
2. **Create app**:
   - App name: `Mood Clip`, description: anything.
   - **Redirect URI:** `https://cim383-wearable-clip.vercel.app/api/spotify/callback` (exactly).
   - API: tick **Web API**.
3. Save, open the app's **Settings**, and copy the **Client ID** and **Client secret**.
4. Under **User Management**, add your own Spotify account email if it isn't listed already.

## 2. Add the keys to Vercel
Project → **Settings → Environment Variables**, for **Production** (and Preview if you test branches):

| Name | Value |
|---|---|
| `SPOTIFY_CLIENT_ID` | the Client ID |
| `SPOTIFY_CLIENT_SECRET` | the Client secret |
| `SPOTIFY_REDIRECT_URI` | optional; only if the site address differs from the one registered above |

Then **redeploy** (Deployments → ⋯ → Redeploy) so the functions see them.

## 3. Connect
Open the website → **Screens → Spotify Now Playing → Connect Spotify**, sign in on Spotify's page,
and approve. You come back to the site with "Spotify connected!". Tap **Show on clip** (or use the
clip's top button) and play something.

## How it works
- The website asks the API for Spotify's sign-in URL (`POST /api/spotify/login`); a one-time random
  `state` is saved in Redis and checked when Spotify sends you back to `/api/spotify/callback`.
- The refresh token is stored only in Redis (`moodclip:spotify_auth`); access tokens are refreshed
  automatically. If you revoke access in your Spotify account, the site shows "not connected".
- The server asks Spotify at most every 10 s (cached in `moodclip:spotify_now`), and only while the
  website is open or the clip is on its Spotify screen.
- The clip receives `{state, title, artist}` (plain ASCII) in its normal check-in reply - never any
  token. It redraws only when the song or its state changes.
- **Disconnect** deletes the tokens from Redis. Rebooting the clip doesn't affect the connection.
