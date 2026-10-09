# Release workflow

Use `pyproject.toml` as the single version source and one signed Git tag for
each release. The PyPI workflow builds and publishes the sdist and wheel from
that tag. The Homebrew tap is this repository: its root `Formula/terrascope.rb`
reads the project version from `pyproject.toml` and uses the matching tag. Its
`head` source follows `main` for pre-release installs. The Nix recipe builds
from the current checkout. The Arch `terrascope-git` recipe follows `main` and
derives its package version from Git tags and commits; it remains a draft until
reviewed and submitted to the AUR.

## One-time setup

1. Create the `pypi` GitHub Actions environment in the repository settings.
2. On PyPI, configure a Trusted Publisher for this repository and the workflow
   `.github/workflows/release.yml`, using the `pypi` environment. No PyPI token
   needs to be stored in GitHub secrets.
3. The project repository is the Homebrew tap. Keep the root
   `Formula/terrascope.rb` in place; it reads its stable version from
   `pyproject.toml`, so no separate tap copy or version edit is needed.

## Release a version

1. Create a release branch from `main`, update `project.version` in
   `pyproject.toml`, and update user-facing release notes. Open a pull request
   and merge it after review.
2. From the updated `main`, create and push a signed version tag (configure
   Git tag signing first). For example:

   ```bash
   git switch main
   git pull --ff-only
   version="$(python -c 'import tomllib; from pathlib import Path; print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"])')"
   git tag -s "v$version" -m "Release $version"
   git push origin "v$version"
   ```

3. The tag starts `.github/workflows/release.yml`. It builds both Python
   distributions, checks their metadata, then publishes the exact build
   artifacts to PyPI through Trusted Publishing. Confirm the release appears
   on PyPI before moving on.
4. After the tag is pushed, Homebrew users can run `brew update` and install the
   matching stable formula. For the current untagged `main`, they can opt into
   `brew install --HEAD a-shygun/terrascope/terrascope`.
5. Review the Arch VCS recipe before submitting `terrascope-git` to the AUR.
   Its source and `pkgver()` follow the repository's `main` branch and tags.
   The Nix recipe reads the version from `pyproject.toml` and builds from the
   checkout; update `packaging/nix/flake.lock` only when refreshing nixpkgs.

Do not reuse a published PyPI version or move a release tag. If a release has a
packaging defect, increment the version and publish a new tag. Keep PyPI
publishing credentials out of the repository; the workflow uses a PyPI
Trusted Publisher with the `pypi` environment.
