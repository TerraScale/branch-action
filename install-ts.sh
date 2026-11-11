#!/usr/bin/env bash
set -euo pipefail
version=0.0.58
case "${RUNNER_OS:-}/${RUNNER_ARCH:-}" in
  Linux/X64) platform=linux_amd64 sha256=8cb62b2f6bf609fa458d8fa9a640c50cca84a11119bdb4da08ce838ea9eb8cdf ;;
  Linux/ARM64) platform=linux_arm64 sha256=7d7e064ab290a573af0492d17abc356423453f434477059a3c533d9afad56d9a ;;
  macOS/X64) platform=darwin_amd64 sha256=30211aa5a8bffefb1ae5d380041f9992fb9bd4871c4c397e43fb1936139ba4d1 ;;
  macOS/ARM64) platform=darwin_arm64 sha256=155caedf6a217244f140e4f87845bc9f7cfe68ffc9281f7789373c78abb6593c ;;
  *) echo "::error::ts $version is released for Linux and macOS runners on X64 or ARM64, not ${RUNNER_OS:-unset} ${RUNNER_ARCH:-unset}." >&2; exit 1 ;;
esac
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
archive="$work/ts_$platform.tar.gz"
curl --fail --silent --show-error --location --retry 2 \
  "https://github.com/TerraScale/terrascale/releases/download/sdk/go/v$version/ts_$platform.tar.gz" \
  --output "$archive"
actual=$(openssl dgst -sha256 "$archive" | awk '{print $NF}')
if [ "$actual" != "$sha256" ]; then
  echo "::error::ts_$platform.tar.gz of ts $version has SHA-256 $actual, not the pinned $sha256; refusing it." >&2
  exit 1
fi
tar -xzf "$archive" -C "$work" ts
installed=$("$work/ts" --version)
if [ "$installed" != "ts $version" ]; then
  echo "::error::ts_$platform.tar.gz holds $installed, not ts $version." >&2
  exit 1
fi
mkdir -p "$HOME/.local/bin"
mv "$work/ts" "$HOME/.local/bin/ts"
echo "$HOME/.local/bin" >> "$GITHUB_PATH"
echo "Installed $installed ($platform, SHA-256 $actual)."
