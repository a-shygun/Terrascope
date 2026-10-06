# Release workflow

Use one version and one signed Git tag for every distribution channel. The
PyPI workflow builds and publishes the sdist and wheel from that tag. Homebrew
is updated in the separate tap repository after the PyPI release is visible.
The Nix recipe is maintained here. The Arch recipe is a draft and must not be
submitted to the AUR until its `SKIP` checksum is replaced with the archive's
SHA-256.

## One-time setup

1. Create the `pypi` GitHub Actions environment in the repository settings.
2. On PyPI, configure a Trusted Publisher for this repository and the workflow
   `.github/workflows/release.yml`, using the `pypi` environment. No PyPI token
   needs to be stored in GitHub secrets.
3. Create a Homebrew tap repository (for example,
   `a-shygun/homebrew-terrascope`) containing `Formula/terrascope.rb`. Keep the
   formula pointed at the matching version tag.

## Release a version

1. Create a release branch from `main`, update `project.version` in
   `pyproject.toml`, and update user-facing release notes. Open a pull request
   and merge it after review.
2. From the updated `main`, create and push a signed version tag (configure
   Git tag signing first). For example:

   ```bash
   git switch main
   git pull --ff-only
   git tag -s v0.2.0 -m "Release 0.2.0"
   git push origin v0.2.0
   ```

3. The tag starts `.github/workflows/release.yml`. It builds both Python
   distributions, checks their metadata, then publishes the exact build
   artifacts to PyPI through Trusted Publishing. Confirm the release appears
   on PyPI before moving on.
4. Update `Formula/terrascope.rb` to the new version tag, then copy it into the
   tap repository. The formula uses the versioned Git tag as its source.
   Homebrew's `brew bump-formula-pr` can calculate/update these fields and open
   a pull request; check `brew bump-formula-pr --help` for the current options.
5. Validate the formula in the tap checkout with `brew audit --strict` and
   `brew test`, then open and merge the tap pull request. Verify a clean install
   with `brew install <tap>/terrascope`.
6. If preparing an Arch package, update `packaging/arch/PKGBUILD`, calculate the
   SHA-256 of the versioned source archive, replace `SKIP`, then build and review
   the package before submitting it to the AUR. The Nix recipe reads the package
   version from `pyproject.toml`; update `packaging/nix/flake.lock` when refreshing
   nixpkgs.

Do not reuse a published PyPI version or move a release tag. If a release has a
packaging defect, increment the version and publish a new tag. Keep PyPI
publishing credentials out of the repository; the workflow uses a PyPI
Trusted Publisher with the `pypi` environment.
