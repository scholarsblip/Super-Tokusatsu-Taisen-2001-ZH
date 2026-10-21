# Battle QA harness

## 0.1.6 baseline — 2026-10-21

Added `tools/run_battle_qa.py`, a dry-run-first wrapper around the existing
PCSX-ReARMed libretro frontend and its built-in HLE BIOS. No proprietary BIOS
is needed. It cold boots the selected image, replays the METAL opening and
executes a real first-stage attack. It does not load another build's save state.

Run the read-only plan first:

```sh
python3 -B tools/run_battle_qa.py --game work/output/NEW_BUILD.cue --output /tmp/stt-new-build-battle
```

Add `--write` after inspecting the plan. The output directory must be fresh.
The 85,000-frame run captures weapon selection, target selection, prebattle
status, attack/death dialogue and return to the map. Baseline execution took
141.34 seconds. Exact timing can change when the opening script changes, so
review captures rather than treating the replay's successful exit as a pass.

The fixed input tail starts at frame 80,030: up, confirm movement, select
attack, select the first weapon, left, confirm the enemy, begin combat.
The frontend's `a` input is the PlayStation Circle button.

Baseline captures and verification are stored locally outside the Git repo at
`../emulator/battle_qa_v0.1.6/`. The original input schedule is included there.
The BIN hash was reread and matches
`537de33d600479d822a298932d0a205f8e948650abf89595e8840c9ed1d5aea6`.

Observed baseline behavior: the hero attacked a Shocker soldier, enemy HP fell
to zero, its death line displayed with an intact portrait, and the game returned
to the map. Existing Japanese battle text remained readable. This does not
verify the later full Chinese battle script.

The baseline revealed a font hazard: battle graphics upload a 128-word-wide
texture at VRAM `(576, 0)`, overwriting the opening prototype's Chinese atlas
at `(640, 48, 64, 192)`. GPU tracing parsed 7,285,419 commands with no errors;
10,282 atlas words changed. The full Chinese build must use a battle-safe font
resource or reload strategy.

A separate first-attack trace found no reads or writes of the proposed extra
CLUT column `(64, 240, 16, 16)`. Native font palettes at x48 were read at
y240, y241, y246 and y247. This only establishes sampled first-attack use;
initial palette loading and other battles require new-build checks.

Save states contain executable, font and texture memory. They are useful for
diagnosis of their matching build, and must not validate changed code or fonts.

## 0.2.1 candidate QA preparation — 2026-10-21

Expanded the cold-boot wrapper to capture the opening, portrait dialogue, map,
weapon menu, prebattle status, attack, death line and return to the map. Added
the optional `--checkpoint-states` frontend argument and seven matching-build
checkpoints so VRAM/font verification can inspect each phase. The state header
and tested version were verified in a two-checkpoint v0.1.6 harness run. These
preparatory checks do not constitute a v0.2.1 game pass.

## 0.2.5 integrated image — 2026-10-21

Cold booted the immutable integrated BIN with SHA-256
`775632e181373ba49a0d6f8132cb2e6d8aaccc3fe40743713af99087f7e4aba5`.
The 85,000-frame run took 143.04 seconds, saved 19 screenshots and seven
matching-build states, and loaded no previous state. Records are in
`../emulator/zh025_coldboot_battle/verification.json` and its capture manifest.

Reviewed the Chinese opening/dialogue, final weapon labels, prebattle enemy
name and effect choices, attack/death scene, and return to the map. Text stayed
inside its windows, portraits remained intact, and weapon/status numbers were
readable. The enemy reached 0/19 HP while the player remained at 66/66 HP, then
the death animation returned to the map. All seven states independently passed
169,008 font color comparisons with zero failures; the exact report is
`work/output/STT2001_ZH_v0.2.5_font_runtime_verification.json`.

This verifies one first-stage S-size melee attack. Other weapons, counterattacks,
giant-unit battles and a full playthrough remain untested. Some compact native
weapon-property abbreviations remain. Fresh HLE data also retains the older
encyclopedia entry gate, so this run does not validate a naturally unlocked
encyclopedia index. Movie playback has a separate verification record.
