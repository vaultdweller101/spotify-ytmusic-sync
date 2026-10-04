# Spotify <--> YouTube Music Bi-Directional Syncer

A Python tool that performs **two-way synchronization** between Spotify and YouTube Music playlists.

- **Intelligent matching**: Uses fuzzy string matching, title cleaning (strips video tags, remasters, etc.), and duration validation.
- **Two-way sync (Union)**: Songs on Spotify missing from YouTube Music are added to YouTube Music; songs on YouTube Music missing from Spotify are added to Spotify.
- **Caching**: Maps matched songs in `sync_cache.json` so repeated runs are fast and don't re-query the APIs unnecessarily.
- **Dry-run mode**: Allows previewing additions before writing to either playlist.

---

## 1. Quick Start

The virtual environment and dependencies are already installed in:
`C:\Users\dngo123\spotify-ytmusic-sync\.venv`

To activate the environment in PowerShell:
```powershell
cd C:\Users\dngo123\spotify-ytmusic-sync
.\.venv\Scripts\Activate.ps1
```

---

## 2. Setup Credentials

### Step 2.1: Spotify Setup
1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and log in.
2. Click **Create App**:
   - **App Name**: `Music Syncer`
   - **Redirect URI**: `http://localhost:8888/callback`
   - **Which API are you planning on using?**: Select `Web API`.
3. Save the app and go to **Settings** to find your **Client ID** and **Client Secret**.
4. Run the setup wizard:
   ```powershell
   python sync.py setup-spotify
   ```
   *This saves the credentials into `.env` and opens your browser once to authorize playlist permissions.*

### Step 2.2: YouTube Music Setup
YouTube Music requires authentication to view and modify your private playlists.

**Recommended Method (Browser Headers):**
1. Open Chrome, Edge, or Firefox and go to [music.youtube.com](https://music.youtube.com). Make sure you are logged in.
2. Press **F12** to open Developer Tools -> click the **Network** tab.
3. Click any song or playlist in YouTube Music so requests appear in the Network tab.
4. Right-click any request to `music.youtube.com` (such as `browse`), select **Copy** -> **Copy request headers** (or Copy as cURL).
5. Run:
   ```powershell
   ytmusicapi browser
   ```
   Paste the headers into your terminal and press `Enter` (or `Ctrl+Z` / `Enter` to finish). This creates `browser.json`.

---

## 3. Test Connections

Verify that both services can connect:
```powershell
python sync.py test
```

---

## 4. Running the Sync

### Option A: Preview with Dry Run (Safe Test)
```powershell
python sync.py sync --spotify "<SPOTIFY_PLAYLIST_URL_OR_ID>" --ytmusic "<YTMUSIC_PLAYLIST_URL_OR_ID>" --dry-run
```

### Option B: Run Two-Way Synchronization
```powershell
python sync.py sync --spotify "<SPOTIFY_PLAYLIST_URL_OR_ID>" --ytmusic "<YTMUSIC_PLAYLIST_URL_OR_ID>"
```

### Option C: Save Default Playlists in `.env`
You can save your playlist links in `.env`:
```env
SPOTIFY_PLAYLIST_ID=https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
YTMUSIC_PLAYLIST_ID=https://music.youtube.com/playlist?list=PLrAlghPGeDAl...
```
Then simply run:
```powershell
python sync.py sync
```

---

## CLI Options

| Argument | Description | Default |
|---|---|---|
| `-s`, `--spotify` | Spotify playlist URL or ID | `.env` value or prompt |
| `-y`, `--ytmusic` | YouTube Music playlist URL or ID | `.env` value or prompt |
| `--dry-run` | Compare playlists and preview matches without modifying anything | `False` |
| `--min-score` | Minimum match similarity threshold (0 - 100) | `70.0` |
| `--cache` | Path to cached track matches file | `sync_cache.json` |
| `--yt-auth` | Explicit path to YouTube Music auth file | `browser.json` / `oauth.json` |
