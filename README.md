# Ganot8

A native GTK4/libadwaita image annotator for Fedora/GNOME. Highlight a region, block
out a password or a customer name, underline a line of log output, point at a button,
drop a label — then hand the result to someone else.

![An annotated terminal screenshot: a highlighted error line, a redacted API token, two
numbered badges, an arrow and a labelled callout](docs/images/example.png)

*Produced by Ganot8's own export path — highlight, solid redaction, numbered badges,
arrow and a text label with a background plate.*

GNOME Screenshot captures; nothing on the desktop annotates. Ganot8 is that missing
half.

## Why it's built the way it is

The main input is screenshots, and screenshots carry secrets — tokens, customer names,
internal hostnames. So redaction is treated as a **privacy-correctness feature, not a
drawing tool**:

- **A redaction cannot be translucent.** `Redact.draw()` hard-codes alpha to 1.0 and
  ignores opacity entirely, and the sidebar never offers the control. A see-through
  redaction is unexpressible rather than merely discouraged.
- **Blur and pixelate have hard floors** — a pixelate block is never smaller than 8px
  and a blur radius never below 6.0, whatever the strength slider says. Measured on
  dark text over a light field, mean neighbouring-pixel difference falls from 5.29 to
  0.05 (blur) and 0.10 (pixelate), and stays below 0.5 even at the weakest setting.
- **A redaction that cannot be drawn degrades to a solid block**, never to nothing, and
  a style written by a newer build loads as solid. Drawing nothing would silently
  expose what the user asked to hide.
- **Export strips metadata.** EXIF, XMP, GPS and ICC are dropped, and no code path
  embeds annotation data in the output — a redacted region cannot be recovered from an
  exported file. Tests assert both.
- **Project files are flagged as sensitive**, because `.ganot8` retains the pristine
  original. A banner appears whenever a project containing redactions is open, and
  **Burn In Redactions** composites them into the source so the saved project no longer
  holds the hidden pixels.

Editing is **non-destructive**: annotations are vector objects over untouched source
pixels, stored in image coordinates so zoom and window size never affect output. The
on-screen canvas and the flattened export share one drawing routine, so what you export
is what you saw.

## Tools

Select · Highlight · Redact (solid, blur or pixelate) · Underline · Arrow · Text · Box ·
Ellipse · Freehand · Numbered badges · Crop, plus rotation.

Images come in by Open, drag-and-drop, clipboard paste, in-app screenshot through the
XDG portal, or a path on the command line. Output is PNG, JPEG, WEBP, AVIF, GIF, TIFF
or BMP, inferred from the extension you choose.

## Installing

Three ways, in increasing order of commitment.

**From the source tree** — nothing is installed:

```bash
./run.sh                 # bootstraps the venv, compiles the schema, runs in place
./run.sh screenshot.png  # or open a file straight away
```

**For one user**, registering the desktop entry, icon, MIME rule and schema under
`~/.local` with no root:

```bash
./install-user.sh            # --uninstall reverses it
```

**System-wide**, with Meson:

```bash
meson setup _build --prefix=/usr -Dpython=/usr/bin/python3
meson compile -C _build && meson test -C _build
sudo meson install -C _build
```

`-Dpython` matters more than it looks: left unset, `find_program('python3')` will
happily resolve to a version manager's shim, which resolves through the *building*
user's configuration rather than that of the user who runs the app. The build warns
when it sees one.

### Requirements

Runtime libraries come from the system, because PyGObject is only a binding layer and
loads the GTK stack through GObject introspection: `gtk4`, `libadwaita`,
`gdk-pixbuf2`, `librsvg2` and `glib2`. The code requires the GTK 4 and libadwaita 1
APIs and declares no tighter minimum; it is developed against gtk4 4.22 and libadwaita
1.9 on Fedora 44. `gtk4-devel` is **not** needed — the typelibs ship in the runtime
package.

Python dependencies are installed from PyPI into a project-local `.venv`, pinned in
`requirements.txt`, using Python 3.14 via pyenv. Deliberately not from system RPMs: a
`dnf upgrade` should not be able to change the app's behaviour. The PyPI Pillow wheel
is also materially better here — it ships a working AVIF codec, which Fedora's
`python3-pillow` does not.

`pygobject` and `pycairo` are source-only on Linux and compile at install time, so a
few build packages are needed once:

```bash
sudo dnf install gcc glib2-devel cairo-devel cairo-gobject-devel \
                 pkgconf-pkg-config libffi-devel
```

`cairo-gobject-devel` is the one that is easy to miss and not optional — without it the
PyGObject build fails on a missing `cairo-gobject.h`, and it is what lets a Cairo
context cross the introspection boundary into the draw callback, which is how the whole
canvas is rendered.

## Keyboard

`Ctrl+O` open · `Ctrl+S` export · `Ctrl+Shift+E` export as · `Ctrl+Shift+S` save
project · `Ctrl+V` paste as new image · `Ctrl+C` copy flattened · `Ctrl+Shift+P` new
from screenshot · `Ctrl+Z` undo · `Ctrl+Shift+Z` redo · `Ctrl+[` / `Ctrl+]` rotate ·
`Ctrl+0` zoom to fit · `Ctrl+1` actual size · `F9` style sidebar · `F1` all shortcuts.

Tools are single keys: `S` select · `H` highlight · `R` redact · `U` underline ·
`A` arrow · `T` text · `B` box · `E` ellipse · `F` freehand · `N` badge · `C` crop.

## Development

```bash
./run-tests.sh           # --strict refuses to run a partial suite
```

The suite splits into display-free tests (logic, image handling, privacy assertions)
and four modules that build real GTK widgets. `run-tests.sh` uses `xvfb-run` when there
is no display; install `xorg-x11-server-Xvfb` to run those headless.

`tests/test_spec.py` checks `docs/SPEC.md` against the code — the annotation table
against the registry, the documented shortcuts against the bound accelerators, the
module tree against the filesystem. The spec had silently fallen out of step twice
before that existed.

Two devtools exist because this machine cannot screenshot the app from outside (GNOME
denies `org.gnome.Shell.Screenshot` to unauthorized callers):
`devtools/shoot_ui.py` renders the live window from inside the process, and
`devtools/render_preview.py` drives the real canvas draw path into an image surface.

**`docs/SPEC.md` is the living design document** — the locked decisions, the data
model, the privacy rules and their rationale, the roadmap, and an open-issues section
that is kept honest about what does not work yet.

## Status

v1 is complete: all seven roadmap phases are implemented and the suite is green. Known
gaps are tracked in section 13 of the spec — the Flatpak manifest has never been built
(no `flatpak-builder` on the development machine), there is no CI pipeline yet, crop has
no adjustable region, and there is no translation groundwork.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
