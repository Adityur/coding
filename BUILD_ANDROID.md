# Build: Android

The Android app is a Capacitor 8 shell around the same `frontend/` files. The Python backend does not run on the phone. The app connects to your server (your PC on the same Wi-Fi, or a hosted server), so credentials never leave that server.

```
Android app (UI)  ──HTTP/WebSocket──▶  python run.py on your PC/server  ──▶  SAMCO / Anthropic
```

## 1. Make the server reachable from the phone

In the server's `.env`:

```
HOST=0.0.0.0
PORT=8000
```

Start it with `python run.py`, find your PC's LAN IP (`ipconfig` on Windows, `ip addr` on Linux/macOS), and allow port 8000 through the firewall. Check from the phone's browser that `http://<PC-IP>:8000/health` loads.

> Only expose port 8000 on a trusted network. The API has no login of its own. For access over the internet, put it behind HTTPS and authentication (a reverse proxy, Tailscale, etc.).

## 2. Quickest path: no build (PWA)

On the phone, open `http://<PC-IP>:8000` in Chrome, then use ⋮ → **Add to Home screen**. It opens full-screen like an app. Offline caching of the app shell needs HTTPS; the app works without it.

## 3. Build the APK

Requirements: Node 22+, Android Studio (latest stable) with Android SDK 36, JDK 21 (bundled with Android Studio).

```bash
cd mobile
npm install
npm run sync          # copies ../frontend into www/ and syncs into android/
npm run open          # opens Android Studio
```

In Android Studio, choose **Build → Build App Bundle(s) / APK(s) → Build APK(s)**.
Or from the command line (with `ANDROID_HOME` set):

```bash
cd mobile && npm run build:debug
# → mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

Install with `adb install app-debug.apk`, or copy the file to the phone.

On first launch the app opens **Settings**. Enter `http://<PC-IP>:8000` as the server address and tap Save.

Run `npm run sync` again after any change in `frontend/`.

## 4. Release build (Play Store / sideload)

1. Create a signing key once and keep it safe; it is git-ignored:
   `keytool -genkey -v -keystore swing-release.jks -keyalg RSA -keysize 2048 -validity 10000 -alias swing`
2. In Android Studio use **Build → Generate Signed App Bundle / APK** with that key, or configure `signingConfigs` in `android/app/build.gradle`.
3. `npm run build:release` → `android/app/build/outputs/bundle/release/app-release.aab`.

## Notes

- `android:usesCleartextTraffic="true"` and `server.androidScheme: "http"` allow plain-HTTP connections to a LAN server. If you serve the API over HTTPS only, you can remove both.
- If you use a custom origin, add it to `CORS_ORIGINS` on the server. The defaults already allow the Capacitor app (`http://localhost`, `capacitor://localhost`, `https://localhost`).
- App ID: `com.swingwatchlist.ai` (in `capacitor.config.json`). Change it before publishing if you want your own namespace.

## Verified here

The Android project was generated with `@capacitor/cli 8.5.3` (compile/target SDK 36, min SDK 24), and the launcher icons were generated from the app icon. A browser test runs the frontend from a separate origin against the API with a configured server address, which is the same code path the Android WebView uses, and it passes. The Gradle/APK build itself was **not** run, because this environment has no Android SDK.
