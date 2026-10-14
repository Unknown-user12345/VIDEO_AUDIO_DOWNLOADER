# Fetch

**Fetch** is a lightweight, cross-platform media downloader built with Python, Kivy, and [yt-dlp](https://github.com/yt-dlp/yt-dlp). It provides a graphical interface for fetching media information, choosing available video quality, and downloading video or audio.

> **Note:** Available downloads depend on the source platform, formats, authentication, and device compatibility. Only download content you have permission to save, and follow applicable platform terms and copyright laws.

## Features

- **Android and desktop UI** built with Kivy.
- **Multiple source support** through yt-dlp, including YouTube, TikTok, Instagram, and X, subject to compatibility and access restrictions.
- **Media preview** with title, uploader, duration, and thumbnail when available.
- **Quality selection** based on the formats detected for the selected media.
- **Audio-only downloads** with platform-appropriate output handling.
- **Cookie-file import** for a Netscape-format `cookies.txt` file when a source requires an authenticated session.
- **Android audio/video merging** using Android `MediaExtractor` and `MediaMuxer` for compatible separate streams.
- **Download progress feedback** including percentage, speed, and ETA when yt-dlp provides them.
- **Custom output folders** with separate preferences for video and audio.
- **Clipboard paste** and support intended for Android shared URLs.

## Requirements

### Desktop

- Python 3
- Kivy
- yt-dlp
- FFmpeg (recommended; needed for desktop audio conversion and stream merging)

### Android

- Android device or emulator compatible with the build configuration
- Buildozer and its Android build dependencies to compile the APK
- Internet access
- Storage permissions appropriate to the Android version

The precise SDK/API requirements are defined in `buildozer.spec`.

## Installation and running on desktop

### 1. Clone the repository

```bash
git clone https://github.com/<YOUR-USERNAME>/<YOUR-REPOSITORY>.git
cd <YOUR-REPOSITORY>
```

Replace the placeholders with your GitHub username and repository name.

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install kivy yt-dlp
```

Install FFmpeg using your operating system's package manager. On Arch Linux:

```bash
sudo pacman -S ffmpeg
```

### 3. Start Fetch

```bash
python main.py
```

## Build the Android APK

Install and configure [Buildozer](https://buildozer.readthedocs.io/) and its required Android build dependencies first. From the project directory, run:

```bash
buildozer android debug
```

If the build succeeds, the APK is normally placed in `bin/`. The exact filename depends on the settings in `buildozer.spec`.

To install the APK on a connected Android device with USB debugging enabled:

```bash
adb devices
adb install -r bin/<your-apk-filename>.apk
```

If ADB reports `unauthorized`, unlock the phone and accept the USB debugging authorization prompt. If no device appears, check the cable, USB connection mode, debugging settings, and Linux USB permissions.

## How to use

1. Open Fetch.
2. Paste a supported media URL, or share a URL to the app on Android if the source app supports sharing.
3. Tap **Fetch Info** and wait for the media information and available quality options.
4. Choose **Video** or **Audio only**.
5. Select a listed quality when downloading video.
6. Optionally change the destination folder.
7. Tap **Download** and monitor the progress indicator.

## Using cookies

Some sources may restrict media information or formats unless you are signed in.

1. Export a Netscape-format `cookies.txt` file from your own browser session using a reputable extension or supported export method.
2. Keep the file private.
3. In Fetch, select **Import** and choose the file.
4. Fetch will use that file for subsequent yt-dlp requests until it is cleared or no longer available.

**Security warning:** Browser cookies can grant access to your account. Never commit `cookies.txt` to GitHub, share it, or include it in screenshots or bug reports. Do not use another person's session cookies. Cookies do not guarantee access to restricted content or any particular resolution.

## Project structure

A basic layout may look like this:

```text
.
├── main.py
├── buildozer.spec
├── README.md
├── .gitignore
└── bin/                 # generated APKs; usually not committed
```

Your repository may contain other files as well.

## Troubleshooting

### No formats are shown or a download fails

- Check that the URL is correct and the source is currently supported by yt-dlp.
- Update yt-dlp to a recent compatible version.
- Check your network connection and the source's access restrictions.
- For content that requires authentication, try your own valid cookie export.
- Some formats or codecs may not work with the Android merging path.

### Desktop audio conversion or merging fails

Confirm FFmpeg is installed and available on your `PATH`:

```bash
ffmpeg -version
```

### Android APK build fails

- Read the first meaningful error in the Buildozer output.
- Verify the SDK, NDK, Java, and Buildozer configuration.
- Check that dependencies and Android requirements in `buildozer.spec` are compatible.
- After changing the configuration, rebuild and inspect the new log.

### A downloaded file does not appear in Gallery

Check the selected output folder and Android storage permissions. Gallery visibility and media scanning behavior vary by Android version and destination path.

## Privacy and security

- Treat cookie files as sensitive credentials.
- Avoid sharing URLs containing private tokens.
- Review the permissions requested by the Android build.
- Download only media you are authorized to access and save.

## Limitations

- Website support can change as websites and their access controls change.
- Available resolutions and formats depend on what yt-dlp can retrieve for a particular URL.
- Android merging depends on compatible containers and codecs supported by the device.
- Android storage behavior varies across OS versions.
- Authentication, regional restrictions, and platform policies may prevent some downloads.

## Built with

- [Python](https://www.python.org/)
- [Kivy](https://kivy.org/)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [Buildozer](https://github.com/kivy/buildozer) — Android packaging
- Android `MediaExtractor` and `MediaMuxer` — Android media handling
- [FFmpeg](https://ffmpeg.org/) — desktop media conversion and merging

## Contributing

Issues and pull requests are welcome. When reporting a bug, include:

- Operating system and Android version, if applicable
- Python, Kivy, yt-dlp, and Buildozer versions
- Relevant error output
- Steps to reproduce the issue

**Never include cookies, access tokens, or other private credentials in an issue.**

## License

Add your chosen license before publishing or distributing this project. If you choose an open-source license, add a `LICENSE` file and update this section accordingly.
