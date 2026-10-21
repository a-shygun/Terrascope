# Release workflow

Use `pyproject.toml` as the single version source and one signed Git tag for
each release. The PyPI workflow builds and publishes the sdist and wheel from
that tag. The Homebrew tap is this repository: its root `Formula/terrascope.rb`
reads the project version from `pyproject.toml` and uses the matching tag. Its
`head` source follows `main` for pre-release installs. The Nix recipe builds
from the current checkout. The AUR `terrascope` package tracks tagged releases
and `terrascope-git` follows `main` with a `pkgver()` derived from Git tags
and commits.

Each tag also builds standalone downloads for `linux_x86_64` and
`linux_arm64` (plus macOS tarballs):

- `terrascope_<version>_<platform>.tar.gz` — portable PyInstaller binary
- `terrascope_<version>_<platform>.deb` — Debian/Ubuntu installer
  (`packaging/linux/build_deb.sh`)
- `terrascope_<version>_<platform>.rpm` — Fedora/RHEL/openSUSE installer
  (`packaging/linux/build_rpm.sh`)
- `terrascope_<version>_<platform>.AppImage` — rootless binary with desktop
  entry and icon (`packaging/linux/build_appimage.sh`,
  `packaging/linux/terrascope.desktop`, `packaging/linux/terrascope.png`)

Checksums for all assets are published as `terrascope_checksums.txt`.

## One-time setup

1. Create the `pypi` GitHub Actions environment in the repository settings.
2. On PyPI, configure a Trusted Publisher for this repository and the workflow
   `.github/workflows/release.yml`, using the `pypi` environment. No PyPI token
   needs to be stored in GitHub secrets.
3. The project repository is the Homebrew tap. Keep the root
   `Formula/terrascope.rb` in place; it reads its stable version from
   `pyproject.toml`, so no separate tap copy or version edit is needed.
4. AUR publishing uses `.github/workflows/aur.yml`:
   - Create an AUR account for the maintainer and register an SSH key at
     https://aur.archlinux.org/account.
   - Add the private key as the `AUR_SSH_PRIVATE_KEY` repository secret.
   - Create the empty `terrascope` and `terrascope-git` AUR packages once
     (clone `ssh://aur@aur.archlinux.org/terrascope.git`, commit the initial
     `PKGBUILD`/`.SRCINFO` from `packaging/aur/`, push). Later releases update
     them automatically.
   - Without the secret the workflow still updates
     `packaging/aur/terrascope/PKGBUILD` and `.SRCINFO` in its run log but
     skips the push with instructions.

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
4. The same tag builds the standalone matrix in `release_packages`:
   PyInstaller onefile binaries, portable tarballs, plus `.deb`, `.rpm`, and
   `.AppImage` on Linux. `create_github_release` uploads everything with a
   generated `terrascope_checksums.txt`. Smoke-test the install you care
   about, for example:

   ```bash
   VERSION=0.3.0
   ARCH=linux_x86_64
   sudo apt install ./terrascope_${VERSION}_${ARCH}.deb
   sudo dnf install ./terrascope_${VERSION}_${ARCH}.rpm
   chmod +x ./terrascope_${VERSION}_${ARCH}.AppImage
   ./terrascope_${VERSION}_${ARCH}.AppImage --help
   ```

   Local rebuilds use the same scripts:

   ```bash
   packaging/linux/build_deb.sh --version "$VERSION" --arch amd64 --binary dist/terrascope --output dist
   packaging/linux/build_rpm.sh --version "$VERSION" --arch x86_64 --platform linux_x86_64 --binary dist/terrascope --output dist
   packaging/linux/build_appimage.sh --version "$VERSION" --platform linux_x86_64 --arch x86_64 --binary dist/terrascope --output dist
   ```

5. After the tag is pushed, Homebrew users can run `brew update` and install the
   matching stable formula. For the current untagged `main`, they can opt into
   `brew install --HEAD a-shygun/terrascope/terrascope`.
6. The tag also starts `.github/workflows/aur.yml`, which syncs
   `packaging/aur/terrascope/PKGBUILD` (`pkgver` + upstream tarball `sha256sums`)
   and its `.SRCINFO`, then pushes `packaging/aur/terrascope` and
   `packaging/aur/terrascope-git` to the AUR when `AUR_SSH_PRIVATE_KEY` is set.
   Canonical AUR sources:

   ```text
   packaging/aur/terrascope/PKGBUILD
   packaging/aur/terrascope/.SRCINFO
   packaging/aur/terrascope-git/PKGBUILD
   packaging/aur/terrascope-git/.SRCINFO
   ```

   `packaging/arch/PKGBUILD` mirrors the `-git` recipe for existing checkouts.
   Test them with `makepkg --printsrcinfo` and, on Arch,
   `makepkg -si` or `namcap`. The Nix recipe reads the version from
   `pyproject.toml` and builds from the checkout; update
   `packaging/nix/flake.lock` only when refreshing nixpkgs.

Do not reuse a published PyPI version or move a release tag. If a release has a
packaging defect, increment the version and publish a new tag. Keep PyPI
publishing credentials out of the repository; the workflow uses a PyPI
Trusted Publisher with the `pypi` environment.
