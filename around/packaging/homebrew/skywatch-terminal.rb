class aroundTerminal < Formula
  include Language::Python::Virtualenv

  desc "Braille-rendered terminal world map with live flight tracking"
  homepage "https://github.com/a-shygun/around"
  url "https://files.pythonhosted.org/packages/source/s/around/around-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_SDIST_SHA256"
  license "MIT"

  depends_on "python@3.12"

  # --- Resource blocks (numpy, Pillow, and transitively hatchling's build-time
  # deps are NOT needed at runtime once installed as a wheel) ---
  #
  # Generate the exact set below with:
  #   pip install homebrew-pypi-poet
  #   poet around
  # and paste the emitted `resource` blocks here, replacing the placeholders.

  resource "numpy" do
    url "https://files.pythonhosted.org/packages/source/n/numpy/numpy-REPLACE.tar.gz"
    sha256 "REPLACE"
  end

  resource "pillow" do
    url "https://files.pythonhosted.org/packages/source/P/pillow/pillow-REPLACE.tar.gz"
    sha256 "REPLACE"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/around", "--help"
  end
end
