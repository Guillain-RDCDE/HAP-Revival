#!/usr/bin/env bash
#
# extract_rootfs.sh — turn a NAND dump from the HAP into a browsable rootfs tree.
#
# Run this AFTER the UART session has pulled the flash partitions off the device
# (see docs/10-uart-console.md and docs/14-nand-extract.md). It unpacks the
# JFFS2 rootfs image entirely in userspace with `jefferson` — no root, no kernel
# modules. This matters because WSL2's kernel ships no MTD subsystem, so the
# classic `modprobe mtdram`/`nandsim` + mount route is NOT available there;
# jefferson reads the JFFS2 structure directly.
#
# Usage:
#   tools/extract_rootfs.sh mtd2.img [out_dir]
#   tools/extract_rootfs.sh nand_full.img out/        # full-NAND dump also works
#
# It will:
#   1. ensure `jefferson` is installed (pip --user; offers to install if missing)
#   2. extract the image to <out_dir>/  (default: <image>.extracted/)
#   3. summarise the HAP-specific artifacts found (control daemon, DSP firmware,
#      init scripts, the dropbear binary, etc.)
#
# Tested 2026-06-05 on a synthetic 128KiB-eraseblock little-endian JFFS2 image
# built with mkfs.jffs2 — round-trips files, symlinks and the directory tree.
#
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

IMG="${1:-}"
[ -n "$IMG" ] || die "usage: $0 <nand-or-mtd-image> [out_dir]"
[ -f "$IMG" ] || die "image not found: $IMG"
OUT="${2:-${IMG}.extracted}"

# --- 1. ensure jefferson ---------------------------------------------------
if ! command -v jefferson >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v jefferson >/dev/null 2>&1; then
  echo "jefferson not found. Install it now (pip --user)? [y/N]"
  read -r ans
  case "$ans" in
    y|Y)
      # --break-system-packages is needed on PEP-668 distros (Ubuntu 24.04+).
      pip3 install --user jefferson 2>/dev/null \
        || pip3 install --user --break-system-packages jefferson
      export PATH="$HOME/.local/bin:$PATH"
      ;;
    *) die "jefferson required. Install with: pip3 install --user jefferson" ;;
  esac
fi
command -v jefferson >/dev/null 2>&1 || die "jefferson still not on PATH (try: export PATH=\$HOME/.local/bin:\$PATH)"

# --- 2. extract ------------------------------------------------------------
echo ">> extracting $IMG -> $OUT/"
# jefferson creates the output dir itself and refuses if it already exists.
rm -rf "$OUT"
# Keep jefferson's per-node log but don't drown the summary.
jefferson "$IMG" -d "$OUT" 2>&1 | tail -n 5

# jefferson nests its output under a per-image subdir; find the real rootfs.
ROOT="$(find "$OUT" -maxdepth 3 -type d -name etc -print -quit 2>/dev/null || true)"
ROOT="${ROOT%/etc}"
[ -n "$ROOT" ] || ROOT="$OUT"

# --- 3. summarise the HAP artifacts ----------------------------------------
echo
echo "================ rootfs summary ($ROOT) ================"
total=$(find "$ROOT" -type f 2>/dev/null | wc -l)
echo "files extracted: $total"
echo
echo "-- key HAP artifacts --"
probe() {
  local label="$1"; shift
  local hit
  hit="$(find "$ROOT" \( "$@" \) 2>/dev/null | head -5)"
  if [ -n "$hit" ]; then
    echo "  [found] $label"
    echo "$hit" | sed "s|$ROOT|   |"
  else
    echo "  [  -  ] $label"
  fi
}
probe "Python control daemon"        -ipath '*forza*' -name '*.py'
probe "DSP firmware blobs (dspfw)"   -ipath '*dspfw*'
probe "init scripts"                 -path '*/etc/init.d/*'
probe "dropbear SSH (root lever)"    -iname 'dropbear*'
probe "lighttpd config"              -iname 'lighttpd*'
probe "ScalarWebAPI / web.py app"    -ipath '*web*' -name '*.py'
probe "version banner"               -name 'version' -path '*/etc/*'
echo
echo "Browse it:  ls -R \"$ROOT\""
echo "Next: enable dropbear at boot + drop in the Phase-4 daemon (back up NAND first)."
