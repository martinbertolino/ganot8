#!/usr/bin/env bash
# Register Ganot8 with the desktop for the current user only.
#
# Nothing is installed system-wide and nothing needs root. Everything lands
# under ~/.local, and --uninstall takes it all back out again.
#
# The application still runs perfectly well without this; it is what makes
# Ganot8 appear in the app grid and in Files' "Open With" menu.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

APP_ID="io.github.martinbertolino.Ganot8"
SOURCE_DIR="$PWD"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"

TARGETS=(
    "$DATA/applications/$APP_ID.desktop"
    "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"
    "$DATA/mime/packages/$APP_ID.xml"
    "$DATA/glib-2.0/schemas/$APP_ID.gschema.xml"
    "$BIN/ganot8"
)

refresh_caches() {
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$DATA/applications" || true
    command -v update-mime-database >/dev/null 2>&1 && \
        update-mime-database "$DATA/mime" || true
    command -v gtk4-update-icon-cache >/dev/null 2>&1 && \
        gtk4-update-icon-cache -q -t "$DATA/icons/hicolor" || true
    command -v glib-compile-schemas >/dev/null 2>&1 && \
        glib-compile-schemas "$DATA/glib-2.0/schemas" || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
    for target in "${TARGETS[@]}"; do
        [[ -e "$target" || -L "$target" ]] && rm -f "$target" && echo "removed $target"
    done
    refresh_caches
    echo "Ganot8 unregistered."
    exit 0
fi

mkdir -p "$DATA/applications" \
         "$DATA/icons/hicolor/scalable/apps" \
         "$DATA/mime/packages" \
         "$DATA/glib-2.0/schemas" \
         "$BIN"

# A launcher, because the .desktop entry runs "ganot8" rather than a path.
cat > "$BIN/ganot8" <<LAUNCHER
#!/usr/bin/env bash
exec "$SOURCE_DIR/run.sh" "\$@"
LAUNCHER
chmod +x "$BIN/ganot8"

install -m644 "data/$APP_ID.desktop"   "$DATA/applications/$APP_ID.desktop"
install -m644 "data/icons/hicolor/scalable/apps/$APP_ID.svg" \
                                       "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"
install -m644 "data/$APP_ID.mime.xml"  "$DATA/mime/packages/$APP_ID.xml"
install -m644 "data/schemas/$APP_ID.gschema.xml" \
                                       "$DATA/glib-2.0/schemas/$APP_ID.gschema.xml"
refresh_caches

echo "Ganot8 registered for $USER."
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "note: $BIN is not on your PATH, so the 'ganot8' command will not be found." >&2 ;;
esac
