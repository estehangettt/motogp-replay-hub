#!/usr/bin/env bash
# Membuat HLS multi-resolusi dari video milik Anda agar pemilih kualitas aktif.
# Pakai : bash tools/make_hls.sh video.mp4 media/2026/INA/motogp/RAC
# Butuh : pkg install ffmpeg
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Pakai: bash tools/make_hls.sh <video_input> <folder_output>" >&2
  exit 1
fi
input="$1"
output="$2"
[ -f "$input" ] || { echo "File tidak ditemukan: $input" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg belum ada. Jalankan: pkg install ffmpeg" >&2; exit 1; }

height=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$input" | head -n1)
audio=$(ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 "$input" | head -n1)

# Hanya resolusi yang tidak melebihi sumber (tanpa upscale).
renditions=()
for target in 1080 720 480 360; do
  if [ "$target" -le "$height" ]; then renditions+=("$target"); fi
done
[ "${#renditions[@]}" -gt 0 ] || renditions=("$height")

args=()
map=""
i=0
for r in "${renditions[@]}"; do
  case "$r" in
    1080) bitrate=5000k ;;
    720)  bitrate=2800k ;;
    480)  bitrate=1400k ;;
    *)    bitrate=800k ;;
  esac
  args+=(-map 0:v:0 "-filter:v:$i" "scale=-2:$r" "-b:v:$i" "$bitrate")
  if [ -n "$audio" ]; then
    args+=(-map 0:a:0)
    map+="v:$i,a:$i,name:${r}p "
  else
    map+="v:$i,name:${r}p "
  fi
  i=$((i + 1))
done

mkdir -p "$output"
ffmpeg -hide_banner -y -i "$input" "${args[@]}" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p \
  -force_key_frames "expr:gte(t,n_forced*6)" -sc_threshold 0 \
  -c:a aac -b:a 128k -ac 2 \
  -f hls -hls_time 6 -hls_playlist_type vod \
  -master_pl_name master.m3u8 -var_stream_map "${map% }" \
  -hls_segment_filename "$output/%v/seg_%05d.ts" "$output/%v/index.m3u8"

echo "Selesai: $output/master.m3u8"
