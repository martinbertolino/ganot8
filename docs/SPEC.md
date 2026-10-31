# Ganot8 — Image Annotation App

**Status:** Phase 2 complete · **Last updated:** 2026-10-31

This is the living spec for Ganot8. It is meant to be edited as the project grows;
section 10 is the roadmap, and each phase there is approved and implemented separately.

## Context

There is no tool on this Fedora/GNOME desktop for quickly marking up a screenshot —
highlighting a region, blocking out a password or customer name, underlining a line of
log output, pointing at a button with an arrow, and dropping a short text label — and
then handing the result to someone else. GNOME Screenshot captures; nothing annotates.

Ganot8 is a native GTK4/libadwaita application for exactly that job, designed to be
grown over time rather than finished in one pass. Because the main input will be
screenshots that may contain sensitive data, the design treats redaction as a
privacy-correctness feature, not just a drawing tool.

---

## 1. Locked decisions

| Decision | Choice |
|---|---|
| Name / App ID | **Ganot8** / `io.github.martinb.Ganot8`, binary `ganot8` |
| Stack | Python 3 + GTK 4 + libadwaita (PyGObject), Cairo rendering, Pillow + GdkPixbuf I/O |
| Edit model | **Non-destructive vector annotations** over a pristine source image |
| Save default | `Ctrl+S` exports a flattened copy; the original file is never written implicitly |
| Project file | `.ganot8` (editable, retains original pixels), saved via `Ctrl+Shift+S` |
| Input paths | Open/drag-drop, clipboard paste, in-app screenshot (XDG portal), CLI argument |
| v1 tool set | highlight, redact, underline, arrow, text + crop/rotate, blur/pixelate, box/ellipse/freehand, numbered badges |
| Python | **3.14.8 via pyenv**, isolated in a project-local `.venv` |
| Dependencies | From **PyPI into the venv**, pinned in `requirements.txt` — not from system RPMs |
| Build | Run from source first (`./run.sh`); Meson + Flatpak deferred to a later phase |

## 2. Development environment

Target: Fedora 44 + GNOME. The project is **not** built against system Python packages;
it uses its own pyenv interpreter and virtualenv so dependency versions are ours to
choose and a `dnf upgrade` cannot change the app's behaviour.

### 2.1 Python

**Python 3.14.8 via pyenv**, pinned by a checked-in `.python-version`, with all Python
dependencies installed from PyPI into a project-local `.venv`:

```bash
pyenv local 3.14.8                  # writes .python-version (committed)
python -m venv .venv                # pyenv shim resolves to 3.14.8
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

`run.sh` execs `.venv/bin/python -m ganot8`, so the app never depends on the shell's
active pyenv version or on `/usr/bin/python3`. The venv is **not** created with
`--system-site-packages`: a pyenv venv cannot see Fedora's `/usr/lib64/python3.14`
packages anyway, and relying on that would defeat the point.

### 2.2 Python dependencies (`requirements.txt`)

| Package | Role | Notes |
|---|---|---|
| `pygobject` 3.58.x | GTK4/libadwaita bindings | **sdist only on Linux — compiles at install time** |
| `pycairo` 1.29.x | Cairo drawing | sdist only on Linux; compiles, ~10s |
| `pillow` 13.x | image decode/encode | manylinux wheel, no compiler needed |
| `pillow-heif` | HEIC/HEIF reading | optional extra; pure wheel |
| `pytest` | tests | |
| `pygobject-stubs` | type hints for `gi` | dev-only, improves editor completion |

### 2.3 System packages

Two distinct sets. **Runtime libraries and typelibs** cannot come from PyPI — PyGObject
is only a binding layer and loads the system GTK stack via GObject introspection.
Verified present on this machine:

- `gtk4` 4.22.5, `libadwaita` 1.9.4, `gdk-pixbuf2` 2.44, `librsvg2` 2.62, `glib2` 2.88.4
- Typelibs confirmed in `/usr/lib64/girepository-1.0/`: `Gtk-4.0`, `Adw-1`, `Gdk-4.0`,
  `Gsk-4.0`, `GdkPixbuf-2.0`, `Pango-1.0`, `PangoCairo-1.0`, `cairo-1.0`, `Gio-2.0`
- **`gtk4-devel` is *not* required** — the typelibs ship in the `gtk4` runtime package

**Build dependencies**, needed only to compile `pygobject` and `pycairo` into the venv:

| Package | Provides | Status |
|---|---|---|
| `gcc` | compiler | installed (16.2.1) |
| `glib2-devel` | `girepository-2.0.pc` (PyGObject ≥ 3.52 requirement) | installed (2.88.4) |
| `cairo-devel` | `cairo.pc` | installed (1.18.6) |
| `pkgconf-pkg-config` | pkg-config | installed |
| `libffi-devel` | `libffi.pc` | installed (3.5.2) |
| **`cairo-gobject-devel`** | **`cairo-gobject.pc` / `cairo-gobject.h`** | **must be installed** |

One-time setup command:

```bash
sudo dnf install cairo-gobject-devel
```

> Without it the PyGObject build fails at
> `gi/pygi-foreign-cairo.c:24: fatal error: cairo-gobject.h: No such file or directory`.
> It is not optional: it is what lets a Cairo context cross the GI boundary into the
> `Gtk.DrawingArea` draw callback, which is how the whole canvas is rendered.

`meson`, `ninja`, and `meson-python` are **not** needed as system packages — pip pulls
them as wheels into the build isolation environment.

### 2.4 API availability (verified)

`Gtk.FileDialog`, `Gtk.ColorDialog`, `Gtk.AlertDialog`, `Gtk.GraphicsOffload`,
`Adw.ToolbarView`, `Adw.Dialog`, `Adw.Banner`, `Adw.Toast`,
`Gdk.Clipboard.read_texture_async`, PangoCairo.

## 3. Module layout

```
ganot8/
├── .python-version             # 3.14.8  (pyenv, committed)
├── requirements.txt            # pinned PyPI deps
├── pyproject.toml              # package metadata, pytest + ruff config
├── run.sh                      # bootstraps .venv if absent, then execs it
├── .venv/                      # git-ignored
├── docs/SPEC.md                # this document
├── src/ganot8/
│   ├── __main__.py             # argv -> Application
│   ├── app.py                  # Adw.Application: actions, accels, open/new-from-* handlers
│   ├── window.py               # Adw.ApplicationWindow: ToolbarView, header, tool bar, sidebar
│   ├── canvas.py               # Gtk.DrawingArea: viewport, zoom/pan, Cairo draw, event routing
│   ├── document.py             # Document: source image, annotation list, z-order, dirty flag
│   ├── annotations.py          # dataclasses per annotation type + draw()/hit_test()/handles()
│   ├── geometry.py             # Rect/Point, transforms, handle math, arrow/line hit tolerance
│   ├── history.py              # Command stack: do/undo/redo, drag coalescing
│   ├── render.py               # shared Cairo drawing used by both canvas and export
│   ├── tools/
│   │   ├── base.py             # Tool protocol: on_press/on_motion/on_release/on_key, cursor
│   │   ├── select.py           # select, move, resize via handles, marquee
│   │   ├── highlight.py  redact.py  underline.py  arrow.py  text.py
│   │   ├── shapes.py           # box, ellipse, freehand
│   │   ├── badge.py            # numbered step badges
│   │   └── crop.py             # crop + rotate
│   ├── imageio/
│   │   ├── loader.py           # Pillow-first load, GdkPixbuf fallback
│   │   ├── exporter.py         # flatten -> Pillow -> save, metadata stripped
│   │   └── project.py          # .ganot8 zip container read/write
│   ├── effects.py              # Pillow blur/pixelate patch generation + surface cache
│   ├── portal.py               # org.freedesktop.portal.Screenshot
│   ├── clipboard.py            # paste texture in, copy flattened out
│   └── settings.py             # GSettings wrapper with in-memory fallback
├── data/
│   ├── io.github.martinb.Ganot8.desktop
│   ├── io.github.martinb.Ganot8.gschema.xml
│   ├── icons/…Ganot8.svg
│   └── style.css
└── tests/                      # pytest: geometry, model, history, imageio, project
```

Rationale for `render.py`: the on-screen canvas and the flattened export **must** share
one drawing routine, or exported output will drift from the preview. Screen draw applies
a zoom/pan matrix; export draws at scale 1.0 into an image surface. Same code path.

The converse boundary matters just as much: **selection chrome and tool previews are
drawn by `canvas.py`, never by `render.py`.** Handles, the dashed selection outline and
the marquee are screen-space and must not exist in an export; keeping them outside the
shared path makes that structural rather than something to remember. A test asserts a
flattened export is byte-identical with and without a selection.

## 4. Data model

```python
Document:
    source: PIL.Image.Image          # pristine RGBA pixels, never mutated by tools
    source_path: Path | None
    project_path: Path | None
    annotations: list[Annotation]    # index = z-order, last drawn on top
    crop: Rect | None                # view/export window into source
    rotation: int                    # 0/90/180/270
    dirty: bool
```

All annotation geometry is stored in **source-image pixel coordinates**, never screen
coordinates, so zoom, pan, and window size never affect saved output.

Annotation types (dataclasses sharing a common protocol):

| Type | Geometry | Style |
|---|---|---|
| `Highlight` | rect | colour, alpha (default yellow @ 0.35, `MULTIPLY` operator) |
| `Redact` | rect | style: `solid` \| `blur` \| `pixelate`; colour; strength |
| `Underline` | p0, p1 | colour, width, wavy flag |
| `Arrow` | p0, p1 | colour, width, head size |
| `TextLabel` | anchor point, wrap width | text, Pango font desc, colour, optional filled background + padding |
| `Box` / `Ellipse` | rect | stroke colour/width, optional fill |
| `Freehand` | point list | colour, width |
| `Badge` | centre point, number | fill/text colour, radius |

Every type implements `draw(cr)`, `bounds()`, `hit_test(pt, tol)`, `handles()`,
`move(dx, dy)`, `set_handle(handle, pt)`, plus `to_dict()` / `from_dict()` and
`state()` / `restore()` for undo.

Annotations are declared `@dataclass(eq=False)`, i.e. compared by **identity**. This is
load-bearing, not a detail: with dataclass value equality two boxes of identical
geometry compare equal, so `document.annotations.index()` and `.remove()` match
whichever comes first — deleting one of a pair deleted the wrong one and undo restored
it at the wrong z-position. `restore()` also mutates **in place** rather than returning a
new object, so the selection and any pending command keep valid references across an undo.
Adding a new tool later = one dataclass + one tool class + registry entry; nothing else
changes. This is the main extension seam.

### `.ganot8` project format

A **zip container** (same idea as OpenRaster), so it is one file, inspectable, and
forward-compatible:

```
document.json     {"version": 1, "crop": …, "rotation": 0, "annotations": [ … ]}
source.png        the pristine original, lossless
thumbnail.png     256px flattened preview
```

`version` is checked on load; unknown annotation types are preserved verbatim on
round-trip rather than dropped, so an older build never silently destroys newer work.

## 5. Image I/O

Using PyPI Pillow rather than Fedora's build materially improves this (verified: the
`pillow` 13.0.0 manylinux wheel reports `features.check("avif") == True` and registers
AVIF as both reader *and* writer, whereas `python3-pillow` 12.3.0 on this machine ships
an AVIF reader with **no working codec**). Pillow is therefore the primary path and
GdkPixbuf is a narrow fallback.

**Loading** — Pillow first, GdkPixbuf as safety net:

1. **Pillow** handles PNG, JPEG, GIF, WEBP, TIFF, BMP, ICO, **AVIF**, PPM, TGA, PSD,
   DDS, QOI and more. `pillow-heif` is registered at startup if importable, adding
   **HEIC/HEIF**.
2. On any decode failure, fall back to **GdkPixbuf**, which is already in-process
   because GTK is loaded, so it costs nothing. It uniquely covers **SVG** (via
   librsvg, rendered at its natural size) and **JPEG XL**, and acts as a general
   backstop for anything a future Pillow version drops. Pixbuf pixels are copied into a
   Pillow `Image`, honouring `rowstride` (which is *not* always `width × channels`).
3. EXIF orientation is applied on load via `ImageOps.exif_transpose`, so a phone photo
   appears upright and annotation coordinates match what the user sees.
4. Animated GIF/WEBP: load **frame 0** and show an `Adw.Banner` saying only the first
   frame is annotated. Multi-frame output is out of scope for v1.
5. Everything is normalised to **RGBA** internally.

**Writing** — Pillow only. Export formats: **PNG** (default), **JPEG** (quality slider,
flattened onto white), **WEBP**, **AVIF**, **GIF**, **TIFF**, **BMP**. Format is
inferred from the chosen extension.

### PIL ↔ Cairo conversion (verified, and done without numpy)

numpy is deliberately not a dependency; both directions are expressible with Pillow and
Cairo alone, which was tested before being written into the spec:

- **PIL → Cairo:** Cairo's `FORMAT_ARGB32` is **alpha-premultiplied** and in native byte
  order (B,G,R,A on little-endian). Premultiply with `ImageChops.multiply(channel,
  alpha)` — it computes exactly `(a × b) / 255` — then `Image.merge("RGBA", (b′, g′, r′,
  a))` and `tobytes()` yields a buffer `cairo.ImageSurface.create_for_data` accepts
  directly. The backing `bytearray` must be kept referenced for the surface's lifetime,
  since `create_for_data` does **not** copy. Byte order is selected from `sys.byteorder`.
- **Cairo → PIL:** Pillow's raw decoder has a premultiplied `"BGRa"` mode which
  un-premultiplies on the way in: `Image.frombuffer("RGBA", size, data, "raw", "BGRa",
  stride, 1)`. Round-trip is exact for opaque pixels and within ±1/255 for
  partially-transparent ones (inherent to 8-bit premultiplication), and fully
  transparent pixels come back as `(0,0,0,0)`.
- `format_stride_for_width` is queried rather than assuming `width × 4`.

**Flatten pipeline:** create a Cairo `ImageSurface` at crop/rotation size → draw source →
draw annotations via `render.py` at scale 1.0 → convert ARGB32 premultiplied to Pillow
RGBA (un-premultiply, BGRA→RGBA swap) → `Image.save()` with **no `exif=` and no
`icc_profile=` passed**, so nothing is carried over.

## 6. Privacy rules (enforced in code, not just convention)

1. **Irreversible flattening on export.** Exported images contain composited pixels
   only. The exporter never writes annotation data into any metadata chunk; there is no
   code path that embeds the project JSON in a PNG/JPEG. A redacted region cannot be
   recovered from an exported file.
2. **Metadata stripped on export.** EXIF/XMP/GPS/ICC from the source are dropped.
   Verified post-condition for the test suite: `Image.open(exported).info` contains no
   `exif`, `XML:com.adobe.xmp`, or `icc_profile` keys.
3. **Project files are flagged as sensitive.** `.ganot8` keeps the unredacted original,
   so the save dialog shows an explicit warning line ("this project file still contains
   the original, unredacted image — do not share it"), and an `Adw.Banner` appears
   whenever a project containing `Redact` annotations is open.
4. **Burn-in action.** `Document.burn_in_redactions()` composites redactions directly
   into `source` and removes those annotations, so even the project file no longer holds
   the hidden content. Irreversible beyond the undo stack, so it is confirmed via
   `Gtk.AlertDialog` and clears redo.

Blur/pixelate strength has a sane floor (pixelate block ≥ 8px at image scale, blur
radius scaled to region size) so a "redaction" can't be set to a cosmetically-blurred,
trivially-reversible value. Solid block remains the default style, with a one-line hint
in the UI that solid is the safe choice for sensitive data.

## 7. Interaction & UI

`Adw.ApplicationWindow` → `Adw.ToolbarView`:

- **Header bar:** Open ▾ (Open…, New from Screenshot, Paste), tool-independent
  undo/redo, Export, menu (Save Project, Export As…, Overwrite Original, Burn In
  Redactions, Copy to Clipboard, Preferences, Keyboard Shortcuts, About).
- **Left tool strip:** vertical toggle group — Select, Highlight, Redact, Underline,
  Arrow, Text, Box, Ellipse, Freehand, Badge, Crop.
- **Centre:** `Gtk.DrawingArea` canvas in a `Gtk.ScrolledWindow`; checkerboard outside
  the image, zoom 10%–800% with fit/100% presets, Ctrl+scroll zoom at pointer,
  middle-drag or space-drag pan.
- **Right sidebar (`Adw.PreferencesGroup` rows):** style properties for the active tool
  or current selection — colour (`Gtk.ColorDialogButton`), width, alpha, redact style,
  font (`Gtk.FontDialogButton`), plus Raise/Lower/Delete.
- **Toasts** for export success (with a "Show in Files" action) and errors.

Behaviour: drawing a shape selects it and switches back to Select (so it can be
immediately adjusted); selection shows 8 resize handles plus endpoint handles for
arrow/underline; Escape cancels an in-progress drag; arrow keys nudge 1px, Shift+arrow
10px; Shift constrains to square/45°; double-click a text label to edit in place.

Undo/redo is a command stack covering every mutation including crop, rotate, reorder,
style changes, and burn-in. A drag emits one coalesced command on release, not one per
motion event.

## 8. Keyboard shortcuts

`Ctrl+O` open · `Ctrl+V` paste · `Ctrl+Shift+P` screenshot · `Ctrl+S` export ·
`Ctrl+Shift+S` save project · `Ctrl+Shift+E` export as · `Ctrl+C` copy flattened ·
`Ctrl+Z` / `Ctrl+Shift+Z` undo/redo · `Delete` delete selection ·
`Ctrl+0` / `Ctrl+1` zoom fit / 100% · `Ctrl+-` / `Ctrl+=` zoom ·
`S H R U A T B E F N C` tool shortcuts · `F1` shortcuts window.

## 9. Settings (GSettings, schema `io.github.martinb.Ganot8`)

Last-used colour/width/alpha/font per tool, default redact style, default export format
and JPEG quality, export filename pattern (default `{stem}-annotated.{ext}`), confirm
overwrite, window geometry. Loaded through `settings.py`, which falls back to an
in-memory dict when the schema isn't installed — so running from source without
`glib-compile-schemas` still works.

## 10. Roadmap

Each phase ends with a runnable app and is approved separately.

0. **Spec** — this document, under git. ✅ done
1. **Bootstrap, skeleton & viewing** — venv setup (§2) and `run.sh`; app/window/canvas,
   Pillow+GdkPixbuf loader, PIL↔Cairo bridge, zoom/pan, CLI arg, drag-and-drop,
   PNG export of an unannotated image. ✅ done
2. **Annotation engine** — `annotations.py`, `geometry.py`, `history.py`, Select tool
   (move/resize/marquee/reorder/delete), style sidebar, tool strip. Ships one concrete
   kind, **Box**, with its creation tool: the engine is not demonstrable or testable
   without something to select, and Box is the reference the phase 3 tools copy. ✅ done
3. **The five core tools** — highlight, redact (solid), underline, arrow, text.
4. **Save & export** — flatten pipeline, format/quality options, `.ganot8` container,
   metadata stripping, overwrite-original with confirmation, project warning banner,
   burn-in action.
5. **v1 extras** — crop/rotate, blur/pixelate redaction (`effects.py` with patch cache),
   box/ellipse/freehand, numbered badges.
6. **Desktop integration** — clipboard paste/copy, XDG screenshot portal, `.desktop`
   file + icon + MIME associations so Ganot8 appears under Files' "Open With".
7. **Packaging (deferred)** — Meson build, GResource-bundled UI, Flatpak manifest.

## 11. Verification

- **Automated (`.venv/bin/pytest`, headless, no display needed):** PIL↔Cairo round-trip
  fidelity; geometry and hit-testing;
  annotation `to_dict`/`from_dict` round-trip including unknown-type preservation;
  undo/redo invariants (N operations then N undos restores the initial model);
  `.ganot8` write→read round-trip; loader across generated
  PNG/JPEG/GIF/WEBP/TIFF/BMP/AVIF fixtures plus an SVG fixture to exercise the
  GdkPixbuf fallback and a rowstride-padded pixbuf to exercise the stride handling;
  **privacy
  assertions** — exported file carries no EXIF/XMP/ICC, and pixels under a solid
  redaction equal the fill colour exactly; burn-in mutates `source`.
- **Offscreen render check:** `devtools/render_preview.py` drives the real
  `Canvas._on_draw` into an image surface and writes PNGs at several zoom levels.
  This exists because the canvas **cannot be screenshotted automatically** on this
  machine: GNOME 50 denies `org.gnome.Shell.Screenshot` to unauthorized callers, the
  XDG portal requires user interaction, and Xvfb is not installed. A display must be
  present for `Gtk.init()`, but no window is shown. Use it after any change to drawing,
  scaling or filtering.
- **Manual, per phase:** `./run.sh` and `./run.sh fixture.png`; annotate a real
  screenshot, export, reopen the export to confirm the annotations are baked in; zoom to
  800% and confirm annotations stay pixel-aligned with the image; paste from clipboard
  after a GNOME screenshot; `Ctrl+Shift+P` area capture through the portal; dark/light
  theme switch; `GTK_DEBUG=interactive` for layout issues.
- **Fidelity check:** export at 100% and compare against a canvas screenshot at 100% —
  they should be pixel-identical, which is the regression test for the shared
  `render.py` path.

## 12. Deliberately out of scope for v1

Multi-frame/animated output, layers panel, SVG/PDF vector export, OCR, speech balloons,
image filters beyond blur/pixelate, multi-document tabs, cloud upload, i18n (strings
stay translatable via `_()` from day one, but no catalogues yet).
