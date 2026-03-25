<p align="center">
  <img src="promo.png" alt="Texto Alternativo">
</p>

# FrontLine Lyrics

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)
![Chrome Extension](https://img.shields.io/badge/Chrome_Extension-4285F4?style=for-the-badge&logo=google-chrome&logoColor=white)
![Manifest V3](https://img.shields.io/badge/Manifest_V3-8A2BE2?style=for-the-badge)
![Open Source](https://img.shields.io/badge/Open_Source-4CAF50?style=for-the-badge)

## Introduction
**FrontLine Lyrics** is an open-source tool that brings live, synchronized lyrics straight to your browser. By listening to your computer's system audio, it automatically identifies the song currently playing and displays its lyrics in a floating, draggable overlay. It works seamlessly across any media player playing on your PC.

## Summary of Features
* **Automatic Recognition**: Identifies the music being played on your system's standard audio output.*
* **Synchronized Lyrics**: Fetches time-synced lyrics from LRCLib and displays them.
* **Floating UI**: A draggable, non-intrusive lyrics overlay injected directly into your active browser tab using Shadow DOM.
* **Manual Control**: Built-in search functionality and manual line-syncing if the automatic timing is slightly off.
* **Privacy-First**: No voice or audio data is saved or transmitted. It only uses local audio loopback to generate an anonymous fingerprint for recognition.

## Technologies Used
This project is split into a local Python server and a Chromium-based browser extension.

**Backend (Local Server):**
* **Python**: Core logic and server environment.
* **Flask**: Lightweight local API server to communicate with the extension.
* **PyAudioWpatch**: For capturing system audio (WASAPI loopback) without needing a virtual audio cable.
* **Shazamio**: Asynchronous framework for reverse-engineering the Shazam API.
* **Asyncio & Threading**: For handling background audio listening loops without blocking the local API.
* **Pystray**: System tray icon management.

**Frontend (Browser Extension):**
* **Vanilla JavaScript (ES6)**: Background service workers and content script injection.
* **Manifest V3**: Modern Chrome Extension architecture.
* **HTML/CSS (Shadow DOM)**: Ensures the extension's UI is isolated and doesn't conflict with the styling of the website you are browsing.
* **External APIs**: [LRCLib](https://lrclib.net/) for fetching synchronized `.lrc` lyrics.

---

## Installation & Usage Guide

Because this is an independent, open-source project, the installation process requires a few manual steps.

### How It Works (Briefly)
FrontLine Lyrics comes in two parts that talk to each other:
1. **The Server (`.exe`)**: Runs quietly in the background on your PC. It briefly listens to the audio your computer is playing, identifies the song (like Shazam), and fetches the lyrics.
2. **The Browser Extension**: The visual panel you interact with inside Chrome/Edge, which displays the lyrics in sync.

### Part 1: Installing the Server
1. **Download the Server File**: Download the `FrontLineLyrics.exe` file from the latest Release page.
2. **Run the Application**: Double-click the `.exe` file to start it.
3. **Handle Windows Defender (Important)**:
   * Because this app is new and created by an independent developer, Windows SmartScreen will likely flag it and say "Windows protected your PC."
   * This is completely normal for unsigned apps. To proceed, click **"More info"** and then click **"Run anyway"**.
   * *Note: Your antivirus might also scan it. You can safely allow it.*
4. **Check the System Tray**: You won't see a big window open. Instead, check the bottom-right corner of your screen (near the clock). You should see the FrontLine Lyrics icon in your system tray. This means the server is running successfully!

### Part 2: Installing the Browser Extension
Since the extension isn't on the official Chrome Web Store yet, you need to load it manually. It works on Google Chrome, Microsoft Edge, Brave, and other Chromium-based browsers.

1. **Download and Extract**: Download the extension `.zip` file from the Release page. Extract (unzip) the folder to a safe place on your computer (like your Documents folder).
2. **Open Extension Settings**:
   * **Chrome**: Type `chrome://extensions/` in your address bar and press Enter.
   * **Edge**: Type `edge://extensions/` in your address bar and press Enter.
3. **Enable Developer Mode**: Look for a toggle switch called "Developer mode" (usually in the top right corner) and turn it **ON**.
4. **Load the Extension**:
   * Click the new button that appears called **"Load unpacked"**.
   * Select the folder you extracted in Step 1.
   * The FrontLine Lyrics icon will now appear in your browser's extension list! *Tip: Click the "puzzle piece" icon in your browser and "Pin" FrontLine Lyrics for easy access.*

### Part 3: How to Use FrontLine Lyrics
1. **Open a Standard Website**: The extension cannot run on browser settings pages or empty tabs. Open any regular website (e.g., youtube.com, google.com).
2. **Launch the Panel**: Click the FrontLine Lyrics icon in your browser toolbar. A control panel will drop down.
3. **Accept the Privacy Prompt**: The first time you use it, you will see a privacy notice. FrontLine Lyrics does not record your voice or spy on you. It only captures a temporary mathematical fingerprint of the song's beat to find the correct lyrics. Click **Accept**.
4. **Start Listening**: Play a song on your computer and click the **Listen** button in the extension panel.
5. **Enjoy the Lyrics!**:
   * A movable lyric overlay will appear at the bottom of your screen.
   * You can click and drag the overlay anywhere you like!
   * You can hide the main control panel by pressing `Alt + M` on your keyboard.

---

## Troubleshooting & FAQ

* **The extension says "Server Offline" or has a red dot.**
  This means the browser can't talk to the `.exe`. Make sure you actually opened `FrontLineLyrics.exe`. If it crashed, open it again and click "Retry Connection" in the extension.

* **The app is stuck on "Identifying..." or says "Lyrics not found."**
  * The app needs a few seconds of a clear beat to identify the song. If it's a very long instrumental intro, it might take a moment.
  * Sometimes, the song might be too obscure, or the lyrics database (LRCLib) doesn't have it yet.
  * **Fix**: You can click **Search Lyrics** in the extension panel, type the Artist and Song Name manually, and click "Search" to force it to find the lyrics.

* **My lyrics are slightly out of sync.**
  If the lyrics are a little bit too fast or too slow, click the **Manual Sync** button. A list with all the lyrics will be displayed. Simply click on the part of the song that will be sung, and the app will instantly sync to that exact moment!

* **Nothing happens when I click the extension icon.**
  Make sure you aren't on a `chrome://` page or a blank new tab. The extension needs to inject its code into a live webpage to display the lyrics. Open any normal website and try again.

* **I have no audio devices / The server crashed immediately.**
  The background server relies on your computer's default speakers to "hear" the loopback audio. Make sure your speakers/headphones are plugged in and set as the default playback device in Windows.
