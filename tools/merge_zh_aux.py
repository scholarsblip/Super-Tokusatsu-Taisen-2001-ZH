#!/usr/bin/env python3
"""Reconstruct Chinese movie text from auxiliary MT rows without changing timing.

The legacy subtitle renderer reads the ``en`` leaves, so these keys are retained
in the Chinese manifest. Only the mapped subtitle and credit text is replaced.
Default mode validates everything and previews 20 replacements; --write saves
the movie manifest and the separate graphics string dictionary. This tool does
not render subtitles, insert a patch, or transcribe missing audio.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys


CONTROL = re.compile(r"<[^<>]*>|\[(?:HERO[1-4]|VAR[56])\]|\{[^{}]*\}")
MOVIE_KINDS = {"movie_caption", "movie_credit"}


def read_rows(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        raw = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("rows", raw.get("units"))
    if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
        raise ValueError(f"{path}: expected a record list or an object containing rows")
    return raw


def indexed(rows: list[dict], label: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        uid = row.get("uid")
        if not isinstance(uid, str) or not uid:
            raise ValueError(f"{label}: missing UID")
        if uid in result:
            raise ValueError(f"{label}: duplicate UID {uid}")
        result[uid] = row
    return result


def parent_and_key(document: dict, pointer: str):
    if not isinstance(pointer, str) or not pointer:
        raise ValueError("Missing source_key")
    parts = pointer.split(".")
    node = document
    try:
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        key = int(parts[-1]) if isinstance(node, list) else parts[-1]
        node[key]  # Do not create missing keys.
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid source_key {pointer}") from exc
    return node, key


def movie_text_pointers(source: dict) -> set[str]:
    expected = set()
    for i, clip in enumerate(source["clips"]):
        for j, _ in enumerate(clip["subtitles"]):
            expected.add(f"clips.{i}.subtitles.{j}.en")
    for i, _ in enumerate(source["credit_pages"]):
        expected.update({f"credit_pages.{i}.heading", f"credit_pages.{i}.body"})
    return expected


def prepare(source: dict, mappings: list[dict], translations: list[dict]):
    mapping_by_uid = indexed(mappings, "mapping")
    target_by_uid = indexed(translations, "MT input")
    missing = sorted(mapping_by_uid.keys() - target_by_uid.keys())
    extra = sorted(target_by_uid.keys() - mapping_by_uid.keys())
    if missing or extra:
        raise ValueError(f"MT UID coverage mismatch: missing={missing}, unexpected={extra}")

    output = deepcopy(source)
    movie_pointers = set()
    graphics = {}
    previews = []
    protected = set()
    counts = {"movie_caption": 0, "movie_credit": 0, "image_ui": 0}
    for uid, mapping in mapping_by_uid.items():
        kind = mapping.get("kind")
        if kind not in counts:
            raise ValueError(f"{uid}: unsupported mapping kind {kind!r}")
        original = mapping.get("text")
        target_row = target_by_uid[uid]
        target = target_row.get("zh_CN")
        if not isinstance(original, str) or not original.strip():
            raise ValueError(f"{uid}: empty source")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"{uid}: empty Chinese target")
        source_hash = target_row.get("mt", {}).get("source_sha256")
        if source_hash and source_hash != hashlib.sha256(original.encode("utf-8")).hexdigest():
            raise ValueError(f"{uid}: MT source hash does not match mapping")
        if CONTROL.findall(original) != CONTROL.findall(target):
            raise ValueError(f"{uid}: control sequence changed")
        if re.findall(r"\r\n|\r|\n", original) != re.findall(r"\r\n|\r|\n", target):
            raise ValueError(f"{uid}: explicit source line breaks changed")
        literals = mapping.get("protected_literals", [])
        if not isinstance(literals, list) or not all(isinstance(x, str) and x for x in literals):
            raise ValueError(f"{uid}: invalid protected_literals")
        for literal in literals:
            if not original.count(literal) or original.count(literal) != target.count(literal):
                raise ValueError(f"{uid}: credited name changed: {literal}")
            protected.add(literal)

        pointer = mapping.get("source_key")
        if kind in MOVIE_KINDS:
            if pointer in movie_pointers:
                raise ValueError(f"Duplicate movie source_key {pointer}")
            movie_pointers.add(pointer)
            parent, key = parent_and_key(source, pointer)
            if parent[key] != original:
                raise ValueError(f"{uid}: canonical source text differs at {pointer}")
            if kind == "movie_caption":
                if not re.fullmatch(r"clips\.\d+\.subtitles\.\d+\.en", pointer):
                    raise ValueError(f"{uid}: invalid subtitle source_key {pointer}")
                clip = source["clips"][int(pointer.split(".")[1])]
                if "clip_id" in mapping and mapping["clip_id"] != clip["id"]:
                    raise ValueError(f"{uid}: clip ID mismatch")
                for field in ("start", "end", "voice_end"):
                    if field in mapping and mapping[field] != parent.get(field):
                        raise ValueError(f"{uid}: source {field} mismatch")
            elif not re.fullmatch(r"credit_pages\.\d+\.(heading|body)", pointer):
                raise ValueError(f"{uid}: invalid credit source_key {pointer}")
            dest_parent, dest_key = parent_and_key(output, pointer)
            dest_parent[dest_key] = target
        else:
            # Graphics labels remain independent of the subtitle manifest.
            graphics[uid] = target
        counts[kind] += 1
        previews.append({"uid": uid, "source_key": pointer, "source": original, "zh_CN": target})

    expected = movie_text_pointers(source)
    if movie_pointers != expected:
        raise ValueError("Movie text coverage mismatch: "
                         f"missing={sorted(expected - movie_pointers)}, "
                         f"unexpected={sorted(movie_pointers - expected)}")
    restored = deepcopy(output)
    for pointer in movie_pointers:
        original_parent, original_key = parent_and_key(source, pointer)
        restore_parent, restore_key = parent_and_key(restored, pointer)
        restore_parent[restore_key] = original_parent[original_key]
    if restored != source:
        raise ValueError("Non-text source metadata changed")
    summary = {
        "status": "validated_machine_unreviewed",
        "translation_rows": len(mappings),
        "movie_subtitle_rows": counts["movie_caption"],
        "credit_fields": counts["movie_credit"],
        "graphics_strings": counts["image_ui"],
        "clips": len(source["clips"]),
        "clips_with_subtitles": sum(bool(clip["subtitles"]) for clip in source["clips"]),
        "shared_credit_pages": len(source["credit_pages"]),
        "protected_names_verified": len(protected),
        "ids_timings_layouts_and_metadata_preserved": True,
        "legacy_en_keys_contain_chinese": True,
        "note": "Only available caption and credit text is covered; no new audio transcription.",
    }
    return output, graphics, summary, previews


def write_atomic(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    if json.loads(path.read_text(encoding="utf-8")) != value:
        raise ValueError(f"Saved JSON verification failed: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="MT JSON/JSONL file or directory of M*.json batches")
    parser.add_argument("--mapping", required=True, type=Path, help="Original auxiliary JSON/JSONL with source_key metadata")
    parser.add_argument("--source", required=True, type=Path, help="Canonical English movie manifest")
    parser.add_argument("--output", required=True, type=Path, help="Chinese movie manifest to save with --write")
    parser.add_argument("--graphics-output", type=Path, help="Separate graphics dictionary (default: graphics_aux.zh_CN.json beside output)")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    paths = sorted(args.input.glob("M*.json")) if args.input.is_dir() else [args.input]
    if not paths:
        raise ValueError(f"No M*.json translation batches in {args.input}")
    targets = [row for path in paths for row in read_rows(path)]
    source = json.loads(args.source.read_text(encoding="utf-8"))
    output, graphics, summary, previews = prepare(source, read_rows(args.mapping), targets)
    graphics_output = args.graphics_output or args.output.with_name("graphics_aux.zh_CN.json")
    destinations = [args.output] + ([graphics_output] if graphics else [])
    protected_inputs = {args.source.resolve(), args.mapping.resolve(), *(path.resolve() for path in paths)}
    if len({path.resolve() for path in destinations}) != len(destinations):
        raise ValueError("Movie and graphics output paths must differ")
    if any(path.resolve() in protected_inputs for path in destinations):
        raise ValueError("Output cannot overwrite a source or translation input")
    summary.update({"mode": "write" if args.write else "dry_run", "output": str(args.output),
                    "graphics_output": str(graphics_output) if graphics else None})
    if args.write:
        write_atomic(args.output, output)
        if graphics:
            write_atomic(graphics_output, graphics)
    print(json.dumps({"summary": summary, "preview": previews[:20]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"merge_zh_aux: {exc}", file=sys.stderr)
        raise SystemExit(2)
