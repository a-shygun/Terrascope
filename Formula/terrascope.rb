class Terrascope < Formula
  include Language::Python::Virtualenv

  desc "Braille-rendered terminal world map with live weather and aircraft"
  homepage "https://github.com/a-shygun/terrascope"
  url "https://github.com/a-shygun/terrascope.git", tag: "v0.2.0"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv = virtualenv_create(libexec, "python3.13")
    virtualenv.pip_install "numpy", "Pillow", "PyYAML", "pyshp", buildpath
    bin.install_symlink libexec/"bin/terrascope"
  end

  test do
    assert_match "terrascope", shell_output("#{bin}/terrascope --help")
  end
end
