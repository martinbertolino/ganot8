# The Python package, installed whole into a private directory.
install_subdir(
  'ganot8',
  install_dir: pkglibdir,
  exclude_directories: ['__pycache__', 'tools/__pycache__', 'imageio/__pycache__'],
  exclude_files: ['ganot8.gresource'],
)

# The launcher. Generated rather than shipped, because it has to carry the
# paths chosen at configure time - a script with hard-coded /usr would be
# wrong for every other prefix.
launcher_conf = configuration_data()
launcher_conf.set('PYTHON', python.full_path())
launcher_conf.set('PKGLIBDIR', get_option('prefix') / pkglibdir)
launcher_conf.set('PKGDATADIR', get_option('prefix') / pkgdatadir)
launcher_conf.set('VERSION', meson.project_version())

configure_file(
  input: 'ganot8.in',
  output: 'ganot8',
  configuration: launcher_conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)
