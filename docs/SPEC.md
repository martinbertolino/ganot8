# Ganot8 — Image Annotation App

**Status:** Phase 4 complete · **Last updated:** 2026-10-31

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
├── pyproject.toml              # package metadata, pytest config
├── run.sh                      # bootstraps .venv if absent, then execs it
├── run-tests.sh                # runs the suite; refuses to hide skipped widget tests
├── .venv/                      # git-ignored
├── docs/SPEC.md                # this document
├── devtools/
│   ├── render_preview.py       # drives the real Canvas draw path offscreen
│   └── shoot_ui.py             # renders the live window/sidebar to PNG
├── src/ganot8/
│   ├── __main__.py             # argv -> Application
│   ├── gi_init.py              # pins GI versions; import before any gi.repository
│   ├── app.py                  # Adw.Application: actions, accelerators, file opening
│   ├── window.py               # header bar, tool strip, style sidebar, text popover
│   ├── canvas.py               # DrawingArea: zoom/pan, selection, tool dispatch
│   ├── dialogs.py              # export options (FileDialog takes no custom widgets)
│   ├── document.py             # source image, annotation list, history, queries
│   ├── annotations.py          # every annotation kind + the registry
│   ├── geometry.py             # Point/Rect, handles, resize, segment distance
│   ├── history.py              # Add/Remove/StateChange/Reorder + undo stack
│   ├── render.py               # shared draw path: canvas and exporter both call it
│   ├── surfaces.py             # PIL <-> Cairo ARGB32 bridge (premultiply/un-premultiply)
│   ├── resources.py            # registers the bundled icon theme path
│   ├── tools/
│   │   ├── base.py             # Tool interface + registry
│   │   ├── select.py           # pick, move, resize, marquee, nudge, double-click
│   │   ├── shapes.py           # RectangleTool / LineTool bases + BoxTool
│   │   ├── highlight.py        # HighlightTool
│   │   ├── redact.py           # RedactTool
│   │   ├── underline.py        # UnderlineTool (forced horizontal)
│   │   ├── arrow.py            # ArrowTool
│   │   ├── text.py             # TextTool
│   │   ├── badge.py            # (phase 5) numbered step badges
│   │   └── crop.py             # (phase 5) crop + rotate
│   ├── imageio/
│   │   ├── loader.py           # Pillow-first load, GdkPixbuf fallback
│   │   ├── exporter.py         # flatten -> Pillow -> save, metadata stripped
│   │   └── project.py          # .ganot8 zip container: save/load, atomic replace
│   ├── effects.py              # blur/pixelate patches, strength floors, cache
│   ├── portal.py               # (phase 6) org.freedesktop.portal.Screenshot
│   ├── clipboard.py            # (phase 6) paste texture in, copy flattened out
│   └── settings.py             # (phase 6) GSettings wrapper with in-memory fallback
├── data/icons/hicolor/scalable/actions/   # bundled symbolic icons
├── data/                       # (phase 6) .desktop, gschema
└── tests/                      # see section 11; support.py holds the shared helpers
```

Entries marked with a phase do not exist yet. `tools/__init__.py` lists the creation
tools explicitly rather than relying on import side effects, because that import order
is what the tool strip shows.

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

| Type | Geometry | Style | Status |
|---|---|---|---|
| `Highlight` | rect | colour, opacity (yellow @ 0.35, `MULTIPLY` operator) | built |
| `Redact` | rect | `style` (`solid`/`blur`/`pixelate`), colour (solid only), strength (blur/pixelate only) — **no opacity, by design** | built |
| `Underline` | start, end | colour, width, opacity, wavy | built |
| `Arrow` | start, end | colour, width, opacity, `head_scale` | built |
| `TextLabel` | anchor, wrap width | text, Pango font string, colour, opacity, optional background plate + padding | built |
| `Box` | rect | colour, width, opacity, filled (**default on**) | built |
| `Ellipse` | rect | stroke colour/width, optional fill | phase 5 |
| `Freehand` | point list | colour, width | phase 5 |
| `Badge` | centre point, number | fill/text colour, radius | phase 5 |

`Redact.style` is serialised already, so adding blur and pixelate in phase 5 needs no
project-format change. `Arrow.head_scale` is likewise stored but not yet exposed in the
sidebar; the head is derived from the stroke width.

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
   into `source` and removes those annotations, so a project saved afterwards no longer
   holds the hidden content. It is one undoable command, confirmed through an
   `Adw.AlertDialog`.

   The dialog is worded to match what the code actually guarantees: *"You can still undo
   this while the image stays open."* Undo keeps the previous pixels in the command
   object, so the hidden content stays reachable **in memory** until the document is
   closed. What burn-in guarantees is about files, not about the running process, and
   claiming otherwise would be a stronger promise than the implementation makes.

`Redact` enforces rule 1 at the drawing level, not by convention: `draw()` hard-codes
alpha to `1.0` and ignores both `opacity` and the alpha channel of `color`, and
`STYLE_OPACITY` is absent from its `style_properties` so the sidebar never offers the
control. A translucent redaction is not a redaction, and this makes that unexpressible
rather than merely discouraged.

Blur and pixelate strength is a 1–100 slider scaled to the region, with **hard floors**
in `effects.py`: a pixelate block is never smaller than 8px and a blur radius never
below 6.0, whatever the slider says. Without them a user could pick a reassuring-looking
value that leaves the content readable. Measured on dark text over a light field, mean
neighbouring-pixel difference — a proxy for how much glyph structure survives — falls
from **5.29 to 0.05 (blur) and 0.10 (pixelate)**, and stays below 0.5 even at strength 1.
Solid block remains the default, and the style row carries the line "A solid block is
the safe choice for anything sensitive".

Two further properties hold the privacy line:

- `Redact.draw()` **degrades to a solid block** whenever the patch cannot be built — no
  `RenderContext`, no cache, a region off the image. Drawing nothing would silently
  expose what the user asked to hide, so the fallback is the safest output, not the
  cheapest.
- An **unrecognised style loads as solid**, so a project written by a newer build cannot
  produce a see-through redaction in this one.

Effects need the pixels underneath, which ordinary drawing does not, so `draw()` takes
an optional `RenderContext` carrying the source image and the document's `EffectCache`.
The cache is keyed on style, strength and the integer rect, and is dropped wholesale
whenever `replace_source` runs — every patch was cut from pixels that no longer exist.

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
- **Right sidebar**, three `Adw.PreferencesGroup`s:
  - **Style** — colour (`Gtk.ColorDialogButton`), font (`Gtk.FontDialogButton`), line
    width, opacity, and the per-kind switches (filled, wavy, background). Only the rows
    in a kind's `style_properties` are shown, and the whole group hides when the active
    tool creates nothing. With a selection the rows edit it; with none they set what the
    active tool will create next.

    Picking a **creation** tool therefore clears the selection, so the panel describes
    what that tool is about to make. Without this the sidebar kept showing the selected
    annotation's options and only corrected itself once the tool was used — and since
    drawing a shape selects it, the very next tool click always hit that case. The
    Select tool keeps the selection, because manipulating what is already there is its
    whole job.
  - **Arrange z-order** — Raise and Lower, with a description line reading "Which
    annotation is drawn on top where they overlap". Enabled only for a single selection,
    since the step is ambiguous otherwise.
  - **Selection** — Delete, plus a summary line ("1 box selected").
- **Toasts** for export success (with a "Show in Files" action) and errors.

Behaviour: drawing a shape selects it and switches back to Select (so it can be
immediately adjusted); selection shows 8 resize handles, or endpoint handles for
arrow/underline and horizontal wrap-width handles for text; Escape cancels an
in-progress drag; arrow keys nudge 1px, Shift+arrow 10px; Shift constrains to
square/45°; an underline is always forced horizontal, since a sloping one is never
intended.

**Text editing** uses a `Gtk.Popover` anchored to the label rather than a text widget
embedded in the canvas. Double-clicking a label reopens it. This is a deliberate
departure from literal in-place editing: a popover keeps working at any zoom and scroll
offset, handles multi-line input, and is the familiar GNOME idiom, whereas an embedded
editor would have to track the zoom/pan transform itself. Committing empty text deletes
the label instead of leaving an invisible annotation behind, and Escape restores the
previous text.

Undo/redo is a command stack covering every mutation including crop, rotate, reorder,
style changes, and burn-in. A drag emits one coalesced command on release, not one per
motion event.

## 8. Keyboard shortcuts

**Implemented:** `Ctrl+O` open · `Ctrl+S` export · `Ctrl+Shift+E` export as ·
`Ctrl+Shift+S` save project · `Ctrl+Z` undo · `Ctrl+Shift+Z` / `Ctrl+Y` redo ·
`Ctrl+A` select all ·
`Ctrl+Shift+A` deselect · `Delete` / `Backspace` delete selection ·
`Ctrl+Page_Up` / `Ctrl+Page_Down` raise / lower · `F9` toggle style sidebar ·
`Ctrl+0` zoom to fit · `Ctrl+1` actual size · `Ctrl+-` / `Ctrl+=` zoom ·
`Ctrl+Q` quit · arrow keys nudge 1px, `Shift`+arrow 10px · `Escape` cancel or deselect.

**Tool keys:** `S` select · `H` highlight · `R` redact · `U` underline · `A` arrow ·
`T` text · `B` box. These are bound to the stateful `win.tool` action, so the detailed
action name carries the tool (`win.tool::highlight`).

**Planned, not yet bound:** `Ctrl+V` paste, `Ctrl+C` copy flattened and
`Ctrl+Shift+P` screenshot (phase 6 — all three are clipboard/portal work, so they
land together); `E` ellipse,
`F` freehand, `N` badge, `C` crop (phase 5); `F1` shortcuts window — note this needs a
`Gtk.ShortcutsWindow` built and a `win.show-help-overlay` action added, which is
currently unassigned to any phase; fold it into phase 6.

## 9. Settings (GSettings, schema `io.github.martinb.Ganot8`)

The shared default line width is **7px**. A hairline looks fine while annotating at
1:1 and then disappears once the screenshot is scaled down into a document or a chat,
which is where these images end up. `Arrow.head_scale` stays at 4.0, so a head keeps
pace with the line rather than being left behind by it.

Style is remembered **per tool** (`Canvas.style_for(name)`), seeded from each
annotation kind's own dataclass defaults — so Highlight starts translucent yellow while
Redact starts opaque black, without either having to be special-cased in the UI.
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
3. **The five core tools** — highlight, redact (solid), underline, arrow, text. ✅ done
4. **Save & export** — `.ganot8` container (atomic replace), project open/save, export
   format + quality dialog, overwrite-original with confirmation, project warning
   banner, burn-in action. ✅ done
5. **v1 extras** — crop/rotate, blur/pixelate redaction (`effects.py` with patch cache),
   box/ellipse/freehand, numbered badges.
6. **Desktop integration** — clipboard paste/copy, XDG screenshot portal, `.desktop`
   file + icon + MIME associations so Ganot8 appears under Files' "Open With",
   a `Gtk.ShortcutsWindow` behind `F1`, and GSettings persistence (section 9).
7. **Packaging (deferred)** — Meson build, GResource-bundled UI, Flatpak manifest.

## 11. Verification

The suite splits in two, and the distinction matters for CI:

- **Display-free** (195 tests as of phase 4) — pure logic and image handling, runnable anywhere:
  `test_surfaces`, `test_geometry`, `test_annotations`, `test_core_annotations`,
  `test_history`, `test_document`, `test_document_annotations`, `test_loader`,
  `test_exporter`, `test_project`, `test_burn_in`, `test_resources`, `test_effects`,
  `test_spec`.
- **Needs a display** (124 tests as of phase 4) — `test_tools`, `test_core_tools`,
  `test_window`, `test_centering`. These construct real GTK widgets, and
  `test_centering` presents a real toplevel and drives genuine allocation cycles.
  `./run-tests.sh` uses `xvfb-run` when there is no display, and `--strict` refuses to
  run a partial suite at all. Install `xorg-x11-server-Xvfb` to execute them headless.

  > **Correction.** An earlier version of this section said these modules "skip
  > themselves rather than fail". That was wrong, and wrong in the dangerous direction.
  > The guard was `Gtk.init_check()`, which **returns `True` with no display**, and in
  > one observed run **segfaulted the interpreter** before returning at all — no
  > `try`/`except` can catch that. Headless, the modules errored or crashed; they did
  > not skip. The guard is now `support.display_available()`, which looks for the
  > display socket and never touches GTK. Verified headless: 182 passed, 4 modules
  > skipped, no crash.

- **What the display-free tests cover:** PIL↔Cairo round-trip
  fidelity; geometry and hit-testing;
  annotation `to_dict`/`from_dict` round-trip including unknown-type preservation;
  undo/redo invariants (N operations then N undos restores the initial model);
  `.ganot8` write→read round-trip; loader across generated
  PNG/JPEG/GIF/WEBP/TIFF/BMP/AVIF fixtures plus an SVG fixture to exercise the
  GdkPixbuf fallback and a rowstride-padded pixbuf to exercise the stride handling;
  **privacy
  assertions** — exported file carries no EXIF/XMP/ICC, and pixels under a solid
  redaction equal the fill colour exactly; burn-in mutates `source`.
- **Centring on open:** `tests/test_centering.py` opens a real toplevel and waits for
  genuine allocation cycles, because the bug it guards against only exists in one. Fit
  zoom is applied on an **idle**, never inline from `notify::page-size`: that handler
  runs during the viewport's size allocation, where a `set_content_*` call is ignored
  for the cycle and leaves the adjustments' `upper` stale. A stale `upper` greater than
  `page_size` makes the ScrolledWindow think it can still scroll, so it pins the child
  at 0 and `halign=CENTER` never applies. Scroll centring (for an image too large to fit
  even at `ZOOM_MIN`) waits further still, until each adjustment's `upper` matches the
  content size actually requested — centring against a stale `upper` lands at the wrong
  offset and is then clamped to the far edge.
- **Forcing layout:** `support.force_layout()` allocates the toplevel at its current
  size to run a layout pass synchronously. Without it the widget tests are at the mercy
  of the compositor: a window that is mapped but never *presented* — the normal case in
  a test run, since the terminal keeps focus — receives no frame callbacks, so its
  `GdkFrameClock` stalls at frame 1 and queued resizes are never processed. Measured: a
  canvas reporting `content_width = 569` stayed allocated at 2400 indefinitely, and the
  centring tests failed for reasons unrelated to the code. `devtools/shoot_ui.py` needs
  the same treatment, and disables stack transitions since animations are driven by that
  same stalled clock.
- **Spec drift:** `tests/test_spec.py` checks this document against the code — the
  section 4 kind table against the annotation registry, the section 8 tool keys against
  the bound accelerators, the section 3 tree against the filesystem (phase-tagged files
  must *not* exist yet), and the display split above against which modules actually call
  `Gtk.init_check()`. The spec had silently fallen out of step twice before this existed.
  Modifier accelerators are deliberately not checked: the spec writes `Ctrl+-` where GTK
  says `<Control>minus`, and a normaliser for that would invent failures rather than
  catch drift.
- **Icon existence:** a test asserts every tool's `icon_name` resolves in the icon
  theme. GTK substitutes a broken-image glyph for a missing icon and logs nothing, so
  this is invisible without an explicit check.
- **UI screenshots:** `devtools/shoot_ui.py` renders the live window and sidebar to PNG
  from *inside* the process — a realized widget is snapshotted to a Gsk render node and
  rendered to a texture by the toplevel's own renderer. This is the way to see the real
  UI here, since GNOME 50 denies `org.gnome.Shell.Screenshot` to unauthorized callers
  and there is no Xvfb. Use it after changing layout, labels or the tool strip.
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

## 13. Open issues

Things that are in scope but unresolved. Decisions get written into the section they
belong to; this is only for what is still open.

### Adw.Banner warns about its own layout when the window is resized

Resizing the window while the banner is visible intermittently logs
`GtkBox reported min width 642 and natural width 459 ... natural size must be >= min
size`. Measured: banner hidden gives 0 warnings over 5 runs, banner visible gives 1 in
roughly every 2. It reproduces with any banner text and with or without the dismiss
button, and the inconsistency is inside libadwaita's own box — the only inputs are a
title string and a button label. No visible breakage, console noise only. Worth a
libadwaita bug report rather than a workaround here.

### No CI pipeline yet

`./run-tests.sh --strict` is the piece that was missing — it exits 2 rather than
reporting success on a partial suite — but nothing runs it automatically. A pipeline
needs `xorg-x11-server-Xvfb` installed on the runner, or 124 tests go unrun.

### Resolved

- **Tool icons that said the wrong thing** — Highlight, Redact and Select now use
  symbolic icons drawn for them in `data/icons/`, registered through
  `resources.install_icons()`. Verified by rendering all seven side by side.
- **Line Width doing nothing for a filled Box** — `Annotation.visible_style_properties()`
  lets a kind drop a control its current state makes inert; `Box` drops line width while
  filled.
- **Closing discarding unsaved annotations silently** — the window now intercepts
  `close-request` and offers Save Project / Discard / Cancel. Exporting deliberately does
  not clear the flag: an exported image is flattened pixels and cannot be reopened for
  editing, so the annotations really are still unsaved, and the dialog says so.
- **Widget tests vanishing on a headless runner** — see the correction in section 11;
  they were never skipping cleanly in the first place.
