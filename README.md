# Spotify <--> YouTube Music Bi-Directional Syncer

A Python tool that synchronizes playlists between **Spotify** and **YouTube Music**.

> [!NOTE]
> **No Spotify Premium Required!**
> In early 2026, Spotify introduced a restriction requiring an active Spotify Premium subscription to register an app in the Spotify Developer Dashboard.
> To solve this, this script includes a **Free / Zero-API Mode**:
> - **Spotify to YouTube Music**: Reads your Spotify playlist directly from the public/shareable web embed—**no API keys, no developer account, and no Spotify Premium needed**. All tracks are automatically searched and added to your YouTube Music playlist.
> - **YouTube Music to Spotify**: If you don't have Premium for the official Web API, the script exports any missing tracks into `spotify_tracks_to_add.txt` with direct search links. You can then add them in Spotify Desktop with a simple `Ctrl + V`.
> - **Full Two-Way API Mode**: If you (or a friend/family member) *do* have Spotify Premium, you can add Developer API keys to `.env` for 100% automated read/write on both platforms.

---

## 1. Quick Start

The virtual environment and dependencies are already set up in:
`C:\Users\dngo123\spotify-ytmusic-sync\.venv`

To activate the environment in PowerShell:
```powershell
cd C:\Users\dngo123\spotify-ytmusic-sync
.\.venv\Scripts\Activate.ps1
```

---

## 2. YouTube Music Setup (Free)

YouTube Music editing is 100% free with any standard Google account.

**Browser Headers Setup (Takes ~30 seconds):**
1. Open Chrome, Edge, or Firefox and go to [music.youtube.com](https://music.youtube.com) (ensure you are logged in).
2. Press **F12** to open Developer Tools -> click the **Network** tab.
3. Click any song or playlist in YouTube Music so requests appear in the Network tab.
4. Right-click any request to `music.youtube.com` (such as `browse`), select **Copy** -> **Copy request headers** (or *Copy as cURL*).
5. Run:
   ```powershell
   ytmusicapi browser
   ```
   Paste the headers into the terminal and press Enter. This creates `browser.json`.

---

## 3. Verify Connections

Test your connection status:
```powershell
python sync.py test
```
*(Spotify will show `Connected to Spotify as: Public Scraper Mode` if running without Premium/API keys).*

---

## 4. Running the Sync

### A. Preview Sync (Dry Run)
Inspect matches without modifying either playlist:
```powershell
python sync.py sync --spotify "<SPOTIFY_PLAYLIST_URL>" --ytmusic "<YTMUSIC_PLAYLIST_URL>" --dry-run
```

### B. Run Synchronization
```powershell
python sync.py sync --spotify "<SPOTIFY_PLAYLIST_URL>" --ytmusic "<YTMUSIC_PLAYLIST_URL>"
```

### C. (Optional) Save Default Playlists in `.env`
Save your playlist links in `.env`:
```env
SPOTIFY_PLAYLIST_ID=https://open.spotify.com/playlist/...
YTMUSIC_PLAYLIST_ID=https://music.youtube.com/playlist?list=...
```
Then simply run:
```powershell
python sync.py sync
```

---

## Summary of Sync Modes

| Mode | Spotify Requirement | Spotify -> YouTube Music | YouTube Music -> Spotify |
|---|---|---|---|
| **Free Mode** (Default) | Free Account (No Premium) | 100% Automatic | Exports links to `spotify_tracks_to_add.txt` (Paste with `Ctrl+V` in Desktop) |
| **API Mode** | Premium Developer App | 100% Automatic | 100% Automatic |
