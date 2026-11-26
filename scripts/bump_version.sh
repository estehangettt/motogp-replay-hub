#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
FILE="android/app/build.gradle"
[ -f "$FILE" ] || { echo "Run from project root."; exit 1; }
python - "$FILE" "${1:-patch}" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
mode = sys.argv[2]
text = path.read_text()
code = int(re.search(r'versionCode\s+(\d+)', text).group(1)) + 1
match = re.search(r'versionName\s+"(\d+)\.(\d+)\.(\d+)"', text)
major, minor, patch = map(int, match.groups())
if mode == "major": major, minor, patch = major + 1, 0, 0
elif mode == "minor": minor, patch = minor + 1, 0
else: patch += 1
text = re.sub(r'versionCode\s+\d+', f'versionCode {code}', text, count=1)
text = re.sub(r'versionName\s+"[^"]+"', f'versionName "{major}.{minor}.{patch}"', text, count=1)
path.write_text(text)
print(f"Version updated: {major}.{minor}.{patch} (code {code})")
PY
