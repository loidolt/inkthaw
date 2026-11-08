# DRAFT Homebrew formula for a personal tap (e.g. `brew tap <owner>/rebind`).
# Not usable until rebind is on PyPI (see the `pypi` job in
# .github/workflows/release.yml); fill in url/sha256 from the published sdist.
#
# Why pip inside a virtualenv instead of one `resource` block per dependency:
# rebind[docling] pulls about 120 packages, including torch (~400 MB on macOS
# arm64), and homebrew-core's resource-per-package style would have to build
# them from source. A tap may install binary wheels instead. A homebrew-core
# submission would need the core-only package (no Docling) or Docling's own
# formula first.
class Rebind < Formula
  include Language::Python::Virtualenv

  desc "Turn scanned PDFs into clean, reflowable EPUBs"
  homepage "https://github.com/loidolt/rebind"
  url "https://files.pythonhosted.org/packages/source/r/rebind/rebind-0.2.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000" # TODO
  license "Apache-2.0"

  depends_on "python@3.12"
  # Builds the EPUB (GPL; installed separately, never bundled).
  depends_on "pandoc"
  # Optional: validates the EPUB. Without it the report notes that validation was skipped.
  depends_on "epubcheck" => :recommended

  def install
    virtualenv_create(libexec, "python3.12")
    # Binary wheels from PyPI: pypdfium2, Pillow, numpy and Docling/torch.
    system libexec/"bin/python", "-m", "pip", "install", "--no-cache-dir",
           "#{buildpath}[docling]"
    bin.install_symlink libexec/"bin/rebind"
  end

  def caveats
    <<~EOS
      Model weights (about 700 MB) are downloaded on first use, or ahead of time with:
        rebind models
      On Apple Silicon the Docling engine uses the GPU (MPS) automatically.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/rebind --version")
    system bin/"rebind", "profiles"
  end
end
