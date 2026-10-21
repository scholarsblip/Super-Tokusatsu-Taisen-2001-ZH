# Third-party notices and inherited rights

This file records provenance and component-specific terms. It is not a new
license for the repository, and does not replace any applicable copyright
notice, license, reserved font name, or upstream condition.

## Upstream project and Chinese additions

This project is a Chinese-port fork of
[retro-trans/Super-Tokusatsu-Taisen-2001](https://github.com/retro-trans/Super-Tokusatsu-Taisen-2001).
The inherited baseline is commit
`b5212eaa4f4cde23e2cab6539611af66d0f82e63` (816 tracked files).
The baseline had no repository-wide `LICENSE`, `COPYING`, or `NOTICE` file.
Public availability and the description “open toolchain” must not be read as
an unverified MIT, GPL, or other blanket license grant.

The upstream README credits translation passes, tooling, and reverse
engineering to Claude (Anthropic), directed by **binhlt0402**, and credits
[retro-trans/SRW-Z](https://github.com/retro-trans/SRW-Z) for the README and
release layout. Retain those credits when carrying the inherited work forward.

The upstream README's distribution policy states:

> This patch is free. Do not sell it, and do not sell anything made with it:
> no pre-patched discs or images, no loaded memory cards or consoles, no
> paywalled or ad-gated downloads.

Those inherited no-sale, no-paywall, and no-ad-gate terms are preserved here.
They do not change the separate licenses of third-party fonts or external
software. No additional repository-wide license is asserted for the Chinese
code, translations, or other additions. Applicable rights remain with their
respective original authors and rights holders; file-specific and inherited
third-party terms continue to apply. This notice does not grant permissions
that those authors or licenses have not granted.

## Game and character rights

Super Tokusatsu Taisen 2001 is © BANPRESTO 2001. Characters and associated
material belong to their respective rights holders, including Ishimori Pro,
Toei, Tsuburaya Pro, Senkosha, Hikari Pro, and others, as acknowledged upstream.
This is an unofficial fan translation and is not endorsed by those entities.

Users must supply their own original game data. The public-source workflow is
designed to regenerate private decoded inputs from that disc, rather than
redistribute ROM images, extracted game data, original Japanese scripts,
BIOS files, or saved emulator memory. Inherited public translation and font
metadata retain their applicable rights; no game ownership is transferred.

## Cubic 11

Included font: `assets/fonts/Cubic11/Cubic_11.ttf`.
Full supplied license and inherited notices:
[`assets/fonts/Cubic11/OFL.txt`](assets/fonts/Cubic11/OFL.txt).

The included font's copyright metadata identifies:

- Copyright (c) 2022–2025 **ACh**.
- Copyright (c) 2022 **Cubic 11 Project Authors**.
- Inherited JF Dot M+H 12: Copyright (c) 2005 **M+ FONTS PROJECT**.
- Inherited M+ BITMAP FONTS: Copyright (c) 2002–2004 **COZ**.

The distribution includes the **SIL Open Font License 1.1** and the inherited
M+ notices. Preserve the full supplied notice file and copyright metadata.
OFL-covered font software and modified font derivatives must remain under
OFL; fonts must not be sold by themselves; any applicable reserved font names
must be respected, and author names must not imply endorsement. The license's
exact terms control. OFL does not automatically relicense the surrounding
Python application or ordinary documents rendered with the font.

`tools/zh_full_font.py` includes small derived bitmap-composition data and
renders game-font atlases from Cubic 11. Its font-derived portions retain the
applicable font terms and attribution above; no blanket software license is
implied by this font-data notice.

## Misaki

Included font: `assets/fonts/Misaki/misaki_gothic.ttf`.
**Copyright (C) 2002–2021 Num Kadoma**.

The complete supplied documents are retained beside the font:
[`misaki.txt`](assets/fonts/Misaki/misaki.txt) and
[`readme.txt`](assets/fonts/Misaki/readme.txt).
The license grants unlimited permission to use, copy, and distribute the
fonts, with or without modification, commercially or noncommercially,
without warranty. Preserve the accompanying copyright and license notices.
The source distribution used here was
[misaki_ttf_2021-05-05.zip](https://littlelimit.net/arc/misaki/misaki_ttf_2021-05-05.zip),
SHA-256 `c1851af85a0a010dd84f40803159c2d8a23feecb6c7e800cfeb5c6edc50da46e`.

## Inherited Gen’ei LateGo P font data

The upstream README identifies **Gen’ei LateGo P** by
[okoneya](https://okoneya.jp/font/genei-latin.html), licensed under **SIL OFL
1.1**, with Latin glyphs from **Linux Biolinum**. Inherited generated data
include `work/font/efont_cells.npz` and `work/font/vwf_cells.npy`.
Those baseline assets have not been removed or relicensed.

A complete copy of the standard license referenced by the upstream README
is supplied as [`work/font/OFL-1.1.txt`](work/font/OFL-1.1.txt). The baseline
did not contain the original font distribution's complete copyright or
reserved-name notices, so the precise font-specific notice set is not claimed
to have been verified here. Obtain and preserve those notices from the original
font distribution before additional font-software redistribution. The generic
OFL text and this attribution do not substitute for missing original notices.

## External runtimes and tools: obtain separately

The Chinese Python wrappers invoke external tools or import independently
installed packages. The local runtime bundles, emulator cores, downloaded
models, and vendor binaries are not included as Chinese-port source additions.
Obtain them from their original projects and follow their own licenses:

- **jPSXdec**: the locally tested package was `v2.1-beta`. Its package license
  is non-commercial, with notice and corresponding-source requirements for
  modified redistributions; bundled components have additional LGPL, CDDL,
  Apache, BSD, and Creative Commons terms. Do not treat it as a permissive
  dependency or copy the local bundle into this repository. Obtain it from
  [jPSXdec](https://github.com/m35/jpsxdec) and retain its complete distribution
  notices in any separately obtained installation.
- **Java/OpenJDK**: the local workflow used a Zulu/OpenJDK 17 runtime. OpenJDK
  is distributed under GPLv2 with the Classpath Exception and additional
  component-specific notices. Obtain Java from its provider; do not vendor
  the local JRE or assume the exception licenses every bundled component.
- **PyAV and FFmpeg**: PyAV uses BSD-3-Clause; its binary wheels may bundle
  FFmpeg libraries with separate, build-dependent terms. Install the required
  Python packages independently and inspect the distributor's FFmpeg license,
  build configuration, notices, and source-compliance information before any
  binary redistribution.
- **Emulators and analysis tools**: obtain the appropriate libretro/
  PCSX-ReARMed core and any jPSXdec, xdelta3, FFmpeg, Capstone, Keystone,
  NumPy, Pillow, xxHash, speech-recognition tools, or models separately as
  required by the workflow. Their licenses remain independent; this notice
  does not sublicense them. Do not include BIOS files, memory cards, save
  states, or RAM/VRAM dumps with the source.

In particular, do not publish a local `tools/movie_runtime/`,
`tools/movie_env/`, `tools/jpsxdec/`, or emulator-core directory as part of a
source upload. Dependency-install instructions and wrappers are preferable to
redistributing those bundles. Consult the setup documentation for supported
versions and the location of each external dependency.
