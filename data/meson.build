# --- the GResource bundle -------------------------------------------------
# Icons travel with the application, so an installed build does not depend on
# the icon cache having been refreshed before it first runs.
gresource = custom_target(
  'gresource',
  input: app_id + '.gresource.xml',
  output: app_id + '.gresource',
  command: [
    glib_compile_resources,
    '--sourcedir', meson.current_source_dir() / 'icons' / 'hicolor',
    '--target', '@OUTPUT@',
    '@INPUT@',
  ],
  install: true,
  install_dir: pkgdatadir,
)

# --- desktop entry --------------------------------------------------------
install_data(
  app_id + '.desktop',
  install_dir: datadir / 'applications',
)

# --- MIME association for .ganot8 ----------------------------------------
install_data(
  app_id + '.mime.xml',
  install_dir: datadir / 'mime' / 'packages',
  rename: app_id + '.xml',
)

# --- settings schema ------------------------------------------------------
install_data(
  'schemas' / (app_id + '.gschema.xml'),
  install_dir: datadir / 'glib-2.0' / 'schemas',
)

# --- application icon -----------------------------------------------------
install_data(
  'icons' / 'hicolor' / 'scalable' / 'apps' / (app_id + '.svg'),
  install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps',
)

# --- AppStream metadata ---------------------------------------------------
# Required by software centres and by Flathub; without it the application is
# installable but invisible to anyone browsing.
metainfo = app_id + '.metainfo.xml'
install_data(
  metainfo,
  install_dir: datadir / 'metainfo',
)

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test(
    'metainfo is valid',
    appstreamcli,
    args: ['validate', '--no-net', '--explain', meson.current_source_dir() / metainfo],
  )
endif

desktop_file_validate = find_program('desktop-file-validate', required: false)
if desktop_file_validate.found()
  test(
    'desktop entry is valid',
    desktop_file_validate,
    args: [meson.current_source_dir() / (app_id + '.desktop')],
  )
endif
