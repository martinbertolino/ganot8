project(
  'ganot8',
  version: '0.1.0',
  meson_version: '>= 1.0.0',
  license: 'GPL-3.0-or-later',
)

app_id = 'io.github.martinbertolino.Ganot8'

prefix = get_option('prefix')
bindir = get_option('bindir')
datadir = get_option('datadir')
libdir = get_option('libdir')

# The Python package goes into a private directory rather than site-packages.
# Ganot8 is an application, not a library: nothing should be able to import it
# by accident, and it must not collide with anything else installed.
pkgdatadir = datadir / meson.project_name()
pkglibdir = libdir / meson.project_name()

# An installed launcher must not point at a version manager's shim: those
# resolve through the invoking user's configuration, which is not the user who
# will run the application. Packagers should pass -Dpython=/usr/bin/python3.
python_option = get_option('python')
if python_option == ''
  python = find_program('python3')
  if python.full_path().contains('shims')
    warning('python3 resolved to ' + python.full_path() + ' - pass -Dpython=/usr/bin/python3 for an installable build')
  endif
else
  python = find_program(python_option)
endif
glib_compile_resources = find_program('glib-compile-resources')

subdir('data')
subdir('src')

# Caches that a desktop reads at login: without refreshing them a freshly
# installed application has no icon, no MIME association and no settings.
gnome_post_install = find_program('meson/post-install.py')
meson.add_install_script(gnome_post_install)

summary({
  'prefix': prefix,
  'bindir': prefix / bindir,
  'python package': prefix / pkglibdir,
  'data': prefix / pkgdatadir,
})
