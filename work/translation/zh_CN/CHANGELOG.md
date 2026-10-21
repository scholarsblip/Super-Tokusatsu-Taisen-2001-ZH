# Simplified Chinese UI data

## Unversioned — 2026-10-21 — public source preparation

- Published Chinese targets, source-hash bindings, glossary and runtime overrides alongside the upstream history and attribution. Excluded original Japanese bodies/speakers from the public selected-source manifest; setup reconstructs them from the user's matching original disc.
- Added dry-run-first setup and input reconstruction helpers. Clean setup reproduces all four historical input objects and refuses wrong source hashes, mismatching fonts and existing source-directory overwrites.
- Made core data/output paths portable. Movie extraction accepts the original disc directly; Java and jPSXdec resolve through environment/PATH without bundled runtimes or mandatory historical builds.
- Replaced the full EVENT230 background dependency with a sparse palette-index restoration delta; applying it to the original disc yields the identical final raster resource.
- Added Chinese README, contribution instructions, dependency versions and third-party notices. Game media, BIOS, runtimes, original dialogue, logs and private QA remain excluded. This source publication creates no GitHub Release.

## 0.2.5 — 2026-10-21 — full machine-translation local test build

- Integrated all 21,508 extracted core units and the complete raster batch from 0.2.2. Added 26 source-pinned runtime corrections for weapon/prebattle labels, effect buttons and combatant/motorcycle unit names, including matching executable labels. All original controls, identifiers and choice structures remain accounted for.
- Preserved the encyclopedia's native category sprites and fixed all three palette moves for four-plane text. A private unused palette in BATTLE538 restores the native dark-on-light book contrast; other 16 font resources are unchanged by this contrast correction. Native CD/GPU diagnostics pass all 512 palette-index checks. The natural registered-save encyclopedia path remains unverified; forced empty-panel footer behavior matches the earlier baseline.
- Inserted Chinese overlays into 28 movies: 4,722 frames and 46,587 video sectors. All inserted frames decode; changed-sector EDC/ECC passes. All XA audio, 46 unedited movies, frame/sector allocations and nonmovie bytes remain unchanged from the exact core baseline.
- Added exact prepared-payload readback from the completed ISO directory and persisted font-plan hashes. Final target BIN SHA-256 is `775632e181373ba49a0d6f8132cb2e6d8aaccc3fe40743713af99087f7e4aba5`.
- Local delivery includes a bare original-source xdelta, a v0.1.6 upgrade xdelta, a shareable patch-only package, matching CUE, Chinese instructions and font notices. A separate short Chinese introduction video uses matching-build game footage. No public release or video upload is implied. Final runtime and delivery checks are recorded in the accompanying verification files.

## 0.2.2 — 2026-10-21 — complete core port, local runtime candidate

- Inserted all 21,508 extracted unique units at 41,437 source coordinates, including story, battle dialogue, encyclopedia, database, music titles and executable UI. Added source-pinned fixes for selectable choices, coin faces, technical abbreviations and default player-name buffers. Retained machine-draft language and provisional terminology statuses.
- Replaced the opening-only resident atlas with 2,658 custom glyphs in four static bitplanes on the native two font pages. Preserved native icon cells and default-name codes; patched glyph lookup and eight active copy/concatenation/width comparisons. Verified exact per-glyph allocation, eight palette styles and all 90 stage RAM limits.
- Patched 17 native font resources. Consumed verified zero padding when expanding raw TIM palettes, preserving fixed encyclopedia RAM pointers. Kept the separate BATTLE537 category-sprite sheet intact. The compressed map-battle font grows only inside its container.
- Rendered 100 raster targets and 1,114 label instances, including all 90 episode cards, menus, encyclopedia headings and compact Critical callouts. Preserved bounds, palette and unrelated pixels; EVENT230 hidden background reconstruction is documented as an approximation.
- Persisted the exact build font allocation and its hash. Static preparation has no missing units or unresolved build issues. Cold-boot battle, encyclopedia and final delivery validation are in progress; movie subtitles remain original in this candidate. No public release created.

## 0.2.0 — 2026-10-21 — machine translation text draft

- Completed the extracted core corpus: 21,508 unique units representing 41,437 frozen occurrences. Preserved the existing 248 prototype rows and translated the other 21,260 with a resumable Google Translate batch tool.
- Used the corrected English reference where its control sequence matches the Japanese; 14 units retain Japanese input. Included 85 additional encyclopedia strings/fragments from the frozen corpus.
- Added 71 existing movie-caption segments, 44 shared-credit text fields and the missing Index heading. Preserved movie timing, clip IDs, metadata and 34 credited names. No additional speech transcription was performed.
- Added cached batching and HTTP recovery in `tools/bulk_mt_zh.py`, strict token/ID checking in `tools/check_zh_mt.py`, editable JSON/TSV and 80-row exports in `tools/export_zh_translation.py`, and metadata-preserving auxiliary reconstruction in `tools/merge_zh_aux.py`.
- Retained the existing executable, manual and graphics Chinese drafts. Corrected machine interpretation of protected identifiers using recorded local overrides; source-specific readable transformations are explicitly documented by the checker.
- Added a quick franchise-name and terminology audit: 424 rules / 795 unique aliases, with live source links, regional variants, semantic translations and provisional statuses distinguished. Canonical bindings are preserved across 8,298 body and 12,090 speaker occurrences. The source glossary has 65 additional pending terms.
- Standardized 5,297 machine speaker fields, applied 270 further Voicer/Fusion Steel/Oyassan term corrections across 250 rows, fixed six unit/word-order errors and seven existing UI/episode-title spellings. Retained the earlier prototype's exact text and recorded its 12 naming differences separately.
- Added exact plain-segment cache migration in `tools/migrate_zh_mt_cache.py`; changed name bindings are restored locally and unchanged source segments reuse the existing translation cache. Reopened and validated the final core, auxiliary and UI outputs.
- This is an unreviewed machine translation dataset. Game reinsertion, full-corpus font coverage, layout and runtime verification remain subsequent work; the playable opening prototype remains version 0.1.6.

## 0.1.6 — 2026-10-21 — local opening prototype

- Unified translated Han, kana, Latin and default-name glyphs at Cubic11's native11px baseline. Portrait dialogue wraps at208px, with at most three body lines; Latin words and runtime name budgets are preserved.
- Moved501 new glyphs to codes1790–2290, preserving original battle/encyclopedia codes0–1789. Expanded the resident MAPMAIN8 upload with a64-word prefix atx640; every original portrait pixel remains at its original physical position. The atlas uses page10,y48–239, leaving its top40px portrait area and palettes intact.
- Fixed missing and striped Chinese glyphs caused by scene graphics overwriting the earlier third-page font. Main and variant font resources retain their native widths.
- Inserted scope:248 unique first-overlay units/271 occurrences,58 executable labels and18 selected raster labels. Other scripts, battle text, database and most graphics remain Japanese.
- Validation:2,294 native lookup cases; all501 atlas cells; allowed-pixel/CLUT checks;80,000-frame cold boot with12 reviewed captures,348,195 Chinese glyph draws and final atlas bytes matching exactly. BIO startup checked separately through10,400frames/five captures. No battle-screen, full-playthrough or all-branch verification is claimed.
- Bare xdelta decode and CHD extract round trips both match BIN SHA-256537de33d600479d822a298932d0a205f8e948650abf89595e8840c9ed1d5aea6. CHD internal raw/overall SHA1 checks pass. No public release created.

## 0.1.5 — 2026-10-20 (local font correction)

- Included the original default-name and VAR6 expansion codes in uniform Cubic11 font rendering; placeholder names no longer depend on literal translation coverage.
- Redrew the 226 ordinary narrow kana, Latin letter, digit and space cells, plus the five wide default-surname cells, at the same 11px size and baseline as translated Chinese. Preserved all encoded values and advances; icon/badge rows are excluded.
- Dry-run checks passed for exact intended glyph cells/bitplanes and the dual-plane lookup routine. Actual emulator validation remains pending in this entry until the final local build is tested.

## 0.1.0 — 2026-10-20

- Translated 58 executable UI strings from original Japanese context; retained all 13 null entries and original offset keys.
- Added 39 manual overrides, seven compact terrain labels, and Chinese text for 101 graphics targets, including 90 episode cards.
- Preserved control tokens, numeric IDs, coordinates, asset paths, and Japanese-reading encyclopedia index categories.
- Checked executable code-slot budgets and JSON structure. Font insertion, raster rendering, and emulator verification remain pending.
- Recorded uncertain glyph decoding and provisional proper-name spellings in `ui_translation_report.json`.
- Translated the next 80 opening-story units, U00080–U00159, in `out/Z0002.json`; examined 240 units with adjacent context and verified exact control tokens, one-row mapping, and null continuation speakers.
- Added 80 continuation/backstory units U00160–U00239 in `out/Z0003.json` and the final eight first-overlay units U00240–U00247 in `out/Z0004.json`; exact runtime tokens, ship identifiers, organization acronyms, and source-null speaker states pass validation.
- Recorded the severe OCR corruption in the three victory/defeat labels U00245–U00247; translations use mission context and the existing English reference and still need direct visual verification.
