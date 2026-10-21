# Build the Chinese version from public source

Use Python 3.11 or newer. The tested core environment is Python 3.12.14,
NumPy 2.3.5, Pillow 12.3.0 and FreeType 2.14.3. Install the Python dependencies:

```sh
python -m pip install numpy==2.3.5 pillow==12.3.0
```

You need your own original Japanese **SLPS-02863** single-track MODE2/2352 BIN:

- Size: `725316816` bytes
- SHA-256: `219d9c4f64caf670b5e400612fa19677ed9a3f59a7ebdb72c12c425412795465`

The original file can be outside the checkout. Keep it unchanged. The setup
script reads it and verifies the complete hash before writing anything.

## Prepare the checkout

From the repository root, inspect the read-only plan:

```sh
python tools/setup_zh_public.py --source-bin "/path/to/original.bin"
```

Then create the local build inputs:

```sh
python tools/setup_zh_public.py --source-bin "/path/to/original.bin" --write
```

Setup verifies the bundled fonts and notices, extracts the user's disc with
`tools/extract_iso.py`, unpacks the four core DAT archives, and reconstructs
the local Chinese build inputs. It copies the licensed Cubic11 and Misaki
fonts from `assets/fonts/` to the `incoming/` paths used by the renderers.
No download or account is required. A separate `--workspace PATH` is available
for isolated bootstrap tests; normal builds should use the checkout default.

Generated private data is under `work/source/`:

| Path | Purpose |
|---|---|
| `disc/` | Files extracted from the original disc |
| `disc_files.json` | Original disc directory metadata |
| `unpacked/` | Original BATTLE, EVENT, MAPMAIN and STAGE entries |
| `zh_inputs/` | Four locally reconstructed source-text inputs |
| `setup_logs/` | Extraction and input-preparation logs |
| `setup_manifest.json` | Original hash, dependency versions, font hashes and input verification |

These files contain original game data and Japanese script. Keep them local;
they are excluded from the public repository. Setup refuses to replace an
existing `work/source` directory or a different existing font. Use a fresh
checkout or a different workspace for another complete setup. On a failed
setup, its temporary directory remains locally for diagnosis.

## Build the core text and graphics

Inspect string/font/layout checks first:

```sh
python tools/build_zh_full.py 0.2.5 --source-bin "/path/to/original.bin" --preflight
```

Create the local BIN/CUE:

```sh
python tools/build_zh_full.py 0.2.5 --source-bin "/path/to/original.bin" --write
```

The default editable files are
`work/translation/zh_CN/translations.zh_CN.json` and the manifests in
`work/translation/zh_CN/full_ui/`. Source-pinned choice/runtime fixes are in
the adjacent `build_*fixes*` and `build_overrides*` files. The builder reads
`work/source/zh_inputs` and writes its image, font plan and verification report
to `work/output/`. Explicit `--translations`, `--inputs`, `--ui-dir`,
`--source-bin` and `--output-dir` overrides are available.

This command builds core text, font and graphics changes. Chinese movie
overlays require the separate native movie pipeline. A completed build and
successful static checks do not establish a full-playthrough QA pass.

## How the public source manifest works

`work/script/occurrences.json` records stable UID, resource, offset,
terminator and font information without Japanese body text. The setup helper
uses those coordinates to decode the user's original disc; it never renumbers
the UIDs with a fresh dump.

`work/translation/zh_CN/chosen_sources.public.jsonl` retains corrected English
references and hashes. It excludes 14 Japanese body fields and 1,918 Japanese
speaker fields, which are reconstructed independently from the disc. Every
decoded disc body and every chosen body/speaker hash is verified. The first
round trip reproduced all four private input JSON objects exactly: 21,423
unique original units, 41,352 ordinary occurrences, 85 extra occurrences and
21,508 chosen sources.

The historical `original_source_sha256` of the 85 later encyclopedia additions
refers to their English reference. That provenance is preserved and labelled;
the separate `disc_body_sha256` always identifies actual original disc text.

For maintainers, `tools/prepare_zh_public_inputs.py export-sources` exports a
new public manifest from a private chosen-source file. `prepare` reconstructs
only the local text inputs from an already extracted disc. Both commands
default to read-only plans and require explicit `--write` and new output paths.
