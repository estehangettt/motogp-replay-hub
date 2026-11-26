# MotoGP Replay Hub Pro

Android-first MotoGP replay interface and local Flask backend, designed to run from Termux.

## Architecture

- Flask backend: `app.py` on `127.0.0.1:5000`
- Frontend: `templates/` and `static/`
- Android WebView wrapper: `android/`
- CI: GitHub Actions builds a debug APK on pushes to `main`
- PulseLive: season/event/circuit data from the read-only MotoGP API

## Important runtime note

The Android wrapper loads `http://127.0.0.1:5000`. The Flask server must be running on the same Android device in Termux. The wrapper does not embed Python or start the Flask process by itself.

## Termux setup

```bash
pkg update -y
pkg install python git openjdk-17 -y
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:5000` in a browser. Keep the Termux process alive while using the WebView APK.

## Android build

GitHub Actions compiles the APK. Before the first push, create one signing keystore and configure repository secrets:

- `ANDROID_DEBUG_KEYSTORE_BASE64`
- `ANDROID_DEBUG_KEYSTORE_PASSWORD`
- `ANDROID_DEBUG_KEY_ALIAS`
- `ANDROID_DEBUG_KEY_PASSWORD`

Generate a persistent keystore locally (Termux):

```bash
keytool -genkeypair -v -keystore motogp-debug.keystore -storetype JKS \
  -alias motogpdebug -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass CHANGE_THIS_STORE_PASSWORD -keypass CHANGE_THIS_KEY_PASSWORD \
  -dname "CN=MotoGP Replay Hub Pro, OU=Android, O=estehangettt, L=Yogyakarta, ST=DIY, C=ID"
base64 -w 0 motogp-debug.keystore
```

Copy the base64 output into GitHub repository Settings → Secrets and variables → Actions. Store the two passwords and alias in the matching secrets. Keep this keystore safe and reuse it for every build; changing it prevents in-place APK updates.

## GitHub

Repository target: `https://github.com/estehangettt/motogp-replay-hub`

```bash
git init
git branch -M main
git add .
git commit -m "Initial MotoGP Replay Hub Pro project"
git remote add origin https://github.com/estehangettt/motogp-replay-hub.git
git push -u origin main
```

## Data and media access

PulseLive circuit layout, flag and numeric fields are read from the event payload. The API documentation notes that circuit data is embedded in `event.circuit`, that the SVG/PNG layout paths are in `circuit.track.assets`, and that flags come from `event.assets` where `type == FLAG`.

The replay scraper extracts regular iframe URLs from the supplied category page. It does not unpack obfuscated scripts or defeat authentication, paywalls, HTTP 403 responses, DRM, or other access controls. The media proxy is intended only for media URLs you are authorized to access and will return upstream access errors as errors.

## Versioning

Increase both `versionCode` and `versionName` in `android/app/build.gradle` for each distributable update. Keep the application ID and signing keystore unchanged to allow an update install over the previous build.

## License and trademarks

This is an unofficial personal learning project. MotoGP and related marks belong to their respective owners. Use official data and media in accordance with their terms.
