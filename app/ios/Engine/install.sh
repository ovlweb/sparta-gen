#!/bin/bash
# Xcode build phase of the app (Runner): Python's standard library, the engine (the repository's spartagen
# package) and its packages go into the app, and every compiled Python module (.so) becomes a signed framework —
# iOS loads native code from frameworks only.  After CPython's Apple testbed (Python.xcframework/build/utils.sh).
set -euo pipefail

here="$PROJECT_DIR/Engine"
xcf="$here/Frameworks/Python.xcframework"
app="$CODESIGNING_FOLDER_PATH"
if [ ! -d "$xcf" ]; then
  echo "error: the engine is not prepared: run app/ios/Engine/prepare.sh first" >&2
  exit 1
fi
case "$EFFECTIVE_PLATFORM_NAME" in
  -iphoneos) slice=ios-arm64; site="$here/site-packages/iphoneos" ;;
  -iphonesimulator) slice=ios-arm64_x86_64-simulator; site="$here/site-packages/iphonesimulator" ;;
  *) echo "error: SpartaGen's engine is not built for $EFFECTIVE_PLATFORM_NAME" >&2; exit 1 ;;
esac
arch=${ARCHS%% *}

sign() {
  # (An unsigned build — flutter build ios --no-codesign — is signed later, as a whole, when it is installed.)
  if [ "${CODE_SIGNING_ALLOWED:-YES}" = NO ] || [ -z "${EXPANDED_CODE_SIGN_IDENTITY:-}" ]; then
    return 0
  fi
  /usr/bin/codesign --force --sign "$EXPANDED_CODE_SIGN_IDENTITY" ${OTHER_CODE_SIGN_FLAGS:-} -o runtime \
    --timestamp=none --preserve-metadata=identifier,entitlements,flags --generate-entitlement-der "$1"
}

# A module's .so, e.g. app_packages/numpy/_core/_multiarray_umath.cpython-313-iphoneos.so, moves into
# Frameworks/numpy._core._multiarray_umath.framework; a .fwork file where it was tells Python where it went.
install_dylib() {   # base (folder the module's name starts in, relative to the app) and the .so
  local base=$1 ext=$2
  local rel=${ext#"$app"/}
  local name
  name=$(echo "${rel#"$base"}" | cut -d . -f 1 | tr / .)
  local fw="Frameworks/$name.framework"
  if [ ! -d "$app/$fw" ]; then
    mkdir -p "$app/$fw"
    cp "$xcf/build/$PLATFORM_FAMILY_NAME-dylib-Info-template.plist" "$app/$fw/Info.plist"
    plutil -replace CFBundleExecutable -string "$name" "$app/$fw/Info.plist"
    plutil -replace CFBundleIdentifier -string "$(echo "$PRODUCT_BUNDLE_IDENTIFIER.$name" | tr _ -)" "$app/$fw/Info.plist"
  fi
  mv "$ext" "$app/$fw/$name"
  echo "$fw/$name" > "${ext%.so}.fwork"
  echo "${rel%.so}.fwork" > "$app/$fw/$name.origin"
  sign "$app/$fw"
}

echo "Python: the standard library ($slice, $arch)"
mkdir -p "$app/python/lib"
rsync -a --delete "$xcf/lib/" "$app/python/lib/"
rsync -a "$xcf/$slice/lib-$arch/" "$app/python/lib/"
echo "the engine: $PROJECT_DIR/../../spartagen"
rsync -a --delete --exclude __pycache__ --exclude '*.pyc' "$PROJECT_DIR/../../spartagen/" "$app/app/spartagen/"
echo "its packages: $site"
rsync -a --delete --exclude __pycache__ "$site/" "$app/app_packages/"

py=$(ls -1 "$app/python/lib" | grep '^python3' | head -1)
find "$app/python/lib/$py/lib-dynload" -name "*.so" | while read -r ext; do
  install_dylib "python/lib/$py/lib-dynload/" "$ext"
done
find "$app/app_packages" -name "*.so" | while read -r ext; do
  install_dylib "app_packages/" "$ext"
done
echo "Python modules as frameworks: $(ls -1d "$app"/Frameworks/*.framework | wc -l | tr -d ' ') frameworks in the app"
