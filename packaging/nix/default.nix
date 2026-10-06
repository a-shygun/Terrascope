{
  buildPythonApplication,
  lib,
  hatchling,
  numpy,
  pillow,
  pyyaml,
  pyshp,
}:
buildPythonApplication (final: {
  pname = "terrascope";
  version = (lib.importTOML ../../pyproject.toml).project.version;
  pyproject = true;
  src = ../..;

  build-system = [ hatchling ];
  dependencies = [ numpy pillow pyyaml pyshp ];
  pythonImportsCheck = [ "terrascope" ];

  meta = {
    description = "A braille-rendered terminal world map with live data layers";
    homepage = "https://github.com/a-shygun/terrascope";
    license = lib.licenses.mit;
    mainProgram = "terrascope";
    platforms = lib.platforms.unix;
  };
})
