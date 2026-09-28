#!/usr/bin/env bash
# Puts SpartaGen in your applications menu (with its icon), for this user. Run it once from the SpartaGen
# folder, wherever you keep it; run it again after moving the folder.  `--remove` takes it out again.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"
if [ "${1:-}" = "--remove" ]; then
  rm -f "$apps/gen.sparta.remix.desktop" "$icons/gen.sparta.remix.png"
  echo "SpartaGen is no longer in the applications menu."
  exit 0
fi
mkdir -p "$apps" "$icons"
cp "$here/data/flutter_assets/assets/icon.png" "$icons/gen.sparta.remix.png"
cat > "$apps/gen.sparta.remix.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=SpartaGen
GenericName=Sparta Remix maker
Comment=Make a Sparta Remix from any video
Exec="$here/spartagen"
Icon=gen.sparta.remix
Terminal=false
Categories=AudioVideo;Audio;Video;
StartupWMClass=gen.sparta.remix
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" >/dev/null 2>&1 || true
echo "SpartaGen is in your applications menu."
