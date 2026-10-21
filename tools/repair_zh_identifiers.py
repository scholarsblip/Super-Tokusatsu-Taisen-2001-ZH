#!/usr/bin/env python3
"""Apply an exact, source-backed repair plan to a separate Chinese MT copy.

Without --write, validate every repair and preview the first 20. Raw engine
batches and their metadata are never modified. The plan pins both source and
target hashes, preventing repairs from silently applying to a different run.
Only zh_CN leaves may change; the output includes a before/after audit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys


CONTROLS = re.compile(r"<[^<>]*>|\[(?:HERO[1-4]|VAR[56])\]|\{[^{}]*\}")


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_rows(path):
    raw = path.read_text(encoding="utf-8")
    data = [json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(raw)
    if isinstance(data, dict):
        data = data.get("rows", data.get("units"))
    if not isinstance(data, list):
        raise ValueError("Source must contain a record list")
    result = {}
    for row in data:
        uid = row["uid"]
        if uid in result:
            raise ValueError(f"Duplicate source UID {uid}")
        result[uid] = row
    return result


def prepare(input_dir, sources, plan):
    if plan.get("unresolved"):
        raise ValueError("Repair plan still has unresolved entries")
    documents = {}
    lookup = {}
    for path in sorted(input_dir.glob("M*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        documents[path.name] = document
        for row in document["rows"]:
            uid = row["uid"]
            if uid in lookup:
                raise ValueError(f"Duplicate target UID {uid}")
            lookup[uid] = (path.name, row)
    if len(lookup) != plan["input_rows"]:
        raise ValueError(f"Target row count changed: {len(lookup)} != {plan['input_rows']}")
    output = deepcopy(documents)
    output_lookup = {row["uid"]: row for doc in output.values() for row in doc["rows"]}
    seen = set()
    audit = []
    for repair in plan["repairs"]:
        uid = repair["uid"]
        if uid in seen:
            raise ValueError(f"Duplicate repair UID {uid}")
        seen.add(uid)
        if uid not in lookup or uid not in sources:
            raise ValueError(f"Missing repair UID {uid}")
        filename, original_row = lookup[uid]
        source = sources[uid]["text"]
        before, after = repair["before"], repair["after"]
        if digest(source) != repair["source_sha256"]:
            raise ValueError(f"{uid}: source SHA differs from repair evidence")
        if original_row.get("mt", {}).get("source_sha256") != digest(source):
            raise ValueError(f"{uid}: MT source SHA differs from canonical source")
        if original_row["zh_CN"] != before or digest(before) != repair["before_sha256"]:
            raise ValueError(f"{uid}: target differs from pinned before text")
        if not isinstance(after, str) or not after.strip() or after == before:
            raise ValueError(f"{uid}: empty or ineffective repair")
        if CONTROLS.findall(before) != CONTROLS.findall(after):
            raise ValueError(f"{uid}: repair would change controls")
        if re.findall(r"\r\n|\r|\n", before) != re.findall(r"\r\n|\r|\n", after):
            raise ValueError(f"{uid}: repair would change explicit line breaks")
        for literal in repair.get("required_source_literals", []):
            if literal not in source:
                raise ValueError(f"{uid}: proposed identifier absent from canonical source: {literal}")
        output_lookup[uid]["zh_CN"] = after
        audit.append(dict(repair, batch=filename, after_sha256=digest(after)))
    if len(seen) != plan["repair_rows"]:
        raise ValueError("Repair row count differs from plan")
    restored = deepcopy(output)
    restored_lookup = {row["uid"]: row for doc in restored.values() for row in doc["rows"]}
    for repair in plan["repairs"]:
        restored_lookup[repair["uid"]]["zh_CN"] = repair["before"]
    if restored != documents:
        raise ValueError("Repair would change fields other than zh_CN")
    summary = {"status": "source_backed_identifier_repairs_machine_unreviewed",
               "input_rows": len(lookup), "batches": len(documents),
               "repaired_rows": len(audit),
               "changed_batches": sum(documents[name] != doc for name, doc in output.items()),
               "source_hashes_and_all_other_metadata_preserved": True,
               "raw_outputs_unchanged": True,
               "not_verified": ["translation meaning", "font coverage", "layout", "insertion/runtime"]}
    return documents, output, {"summary": summary, "repairs": audit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--repairs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        raise ValueError("Output directory must differ from raw input")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Output directory must be absent or empty")
    sources = source_rows(args.source)
    plan = json.loads(args.repairs.read_text(encoding="utf-8"))
    original, output, audit = prepare(args.input, sources, plan)
    audit["summary"].update({"mode": "write" if args.write else "dry_run",
                             "input": str(args.input), "output": str(args.output)})
    if args.write:
        args.output.mkdir(parents=True, exist_ok=True)
        raw_hashes = {}
        for path in sorted(args.input.iterdir()):
            if not path.is_file():
                continue
            raw = path.read_bytes()
            raw_hashes[path.name] = hashlib.sha256(raw).hexdigest()
            destination = args.output / path.name
            if path.name in output and output[path.name] != original[path.name]:
                destination.write_text(json.dumps(output[path.name], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                if json.loads(destination.read_text(encoding="utf-8")) != output[path.name]:
                    raise ValueError(f"Saved output validation failed: {destination}")
            else:
                destination.write_bytes(raw)
                if destination.read_bytes() != raw:
                    raise ValueError(f"Exact copy validation failed: {destination}")
        for filename, original_hash in raw_hashes.items():
            if hashlib.sha256((args.input / filename).read_bytes()).hexdigest() != original_hash:
                raise ValueError(f"Raw input changed during repair: {filename}")
        audit["raw_file_sha256"] = raw_hashes
        (args.output / "identifier_repair_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": audit["summary"], "preview": audit["repairs"][:20]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"repair_zh_identifiers: {exc}", file=sys.stderr)
        raise SystemExit(2)
