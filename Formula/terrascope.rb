class Terrascope < Formula
  include Language::Python::Virtualenv

  desc "Braille-rendered terminal world map with live weather and aircraft"
  homepage "https://github.com/a-shygun/terrascope"

  project_root = File.expand_path("../..", __dir__)
  project_version = File.read(File.join(project_root, "pyproject.toml"))
                         .match(/^version\s*=\s*"([^\"]+)"$/)[1]

  version project_version
  url "https://github.com/a-shygun/Terrascope.git", tag: "v#{project_version}"
  head "https://github.com/a-shygun/Terrascope.git", branch: "main"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv = virtualenv_create(libexec, "python3.13")
    system virtualenv.root/"bin/python", "-m", "pip", "install",
           "--only-binary=:all:", buildpath
    bin.install_symlink libexec/"bin/terrascope"
  end

  test do
    assert_match "terrascope", shell_output("#{bin}/terrascope --help")
  end
end
