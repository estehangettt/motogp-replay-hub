# MotoGP Replay Hub Pro

Aplikasi pribadi: data resmi MotoGP (kalender, sesi, hasil, klasemen, info sirkuit) dan
pemutar untuk video milik Anda sendiri. Tidak berafiliasi dengan MotoGP/Dorna.
Tidak mengambil stream dari situs pihak ketiga. Siaran ulang resmi: VideoPass.

## Menjalankan di Termux

    pkg update -y
    pkg install -y python git gh openjdk-17
    cd ~/motogp-replay-hub
    pip install -r requirements.txt
    termux-wake-lock
    python app.py

Lalu buka aplikasi APK, atau http://127.0.0.1:5000 di browser HP.

## Logo di header

Simpan file logo PNG Anda sebagai `static/img/logo.png`, lalu muat ulang.
File ini tidak ikut di-upload ke GitHub. Merek milik pemiliknya; pakai pribadi saja.

## Menambah video

Letakkan file yang Anda miliki haknya dengan pola:

    media/<tahun>/<KODE_EVENT>/<kelas>/<SESI>.mp4

- kelas: motogp, moto2, moto3
- SESI: FP1, FP2, PR, Q1, Q2, SPR, WUP, RAC
- KODE_EVENT: kode di dropdown GP (aplikasi juga menampilkan path lengkapnya)

Format: MP4 (H.264 + AAC), WebM, atau folder HLS berisi master.m3u8.

Memakai folder di penyimpanan HP:

    termux-setup-storage
    REPLAY_MEDIA_DIR=~/storage/shared/ReplayHub python app.py

## Pemilih resolusi

Aktif untuk HLS multi-resolusi. Buat dari video Anda:

    pkg install -y ffmpeg
    bash tools/make_hls.sh video.mp4 media/2026/INA/motogp/RAC

MP4 biasa hanya punya satu resolusi. Menu More > Uji player memakai stream tes
publik untuk mencoba pemilih kualitas.

## APK

Setiap push ke `main` menjalankan GitHub Actions dan menerbitkan APK di tab
Releases. versionCode mengikuti nomor run.

PENTING:
- `android/app/debug.keystore` harus tetap sama. Jika hilang atau diganti, APK
  baru tidak bisa dipasang sebagai update. Simpan cadangannya.
- Buat repo **private** karena keystore ikut di-commit.
