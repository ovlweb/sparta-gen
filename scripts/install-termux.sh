#!/data/data/com.termux/files/usr/bin/bash
# Sparta Gen on Android, via Termux (https://termux.dev — install it from F-Droid or GitHub).
#
#   curl -fsSL https://raw.githubusercontent.com/TheQSN/sparta-gen/HEAD/scripts/install-termux.sh | bash
#
# Set SPARTAGEN_BRANCH=<branch> to install another branch than the repository default.
#
# Everything runs on the phone: ffmpeg does the cutting/encoding, the GUI opens
# in the phone's browser at http://127.0.0.1:<port>/.
set -e

REPO_URL="${SPARTAGEN_REPO:-https://github.com/TheQSN/sparta-gen}"
BRANCH="${SPARTAGEN_BRANCH:-}"
DEST="$HOME/sparta-gen"

echo "==> Installing packages (python, ffmpeg, numpy, scipy, pillow)…"
pkg update -y
pkg install -y python ffmpeg git python-numpy python-pillow termux-api || true
# scipy is optional (the engine has a pure-numpy fallback) but makes renders faster.
pkg install -y python-scipy || echo "   (python-scipy not available — continuing without it)"

echo "==> Getting Sparta Gen…"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only
else
  if [ -n "$BRANCH" ]; then
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$DEST"
  else
    git clone --depth 1 "$REPO_URL" "$DEST"
  fi
fi

echo "==> Installing the app…"
pip install --no-deps -e "$DEST"
pip install yt-dlp || echo "   (yt-dlp failed to install — URL downloads disabled, local files still work)"

echo "==> Shared storage (to pick videos from your phone)…"
termux-setup-storage || true

mkdir -p "$HOME/.shortcuts"
cat > "$HOME/.shortcuts/SpartaGen" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
spartagen gui
EOF
chmod +x "$HOME/.shortcuts/SpartaGen"

echo
echo "Done! Start it with:   spartagen gui"
echo "(or add the Termux:Widget and tap the 'SpartaGen' shortcut)."
echo "Your phone's videos are under ~/storage/shared/ (e.g. DCIM, Download, Movies)."
