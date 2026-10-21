#!/usr/bin/env python3
"""Prepare private Chinese-build inputs from a public source manifest.

Both subcommands are read-only unless --write is supplied. ``export-sources``
keeps corrected English references, replacing Japanese fields with hashes and
instructions to decode the user's disc. ``prepare`` reconstructs the four
local inputs used by build_zh_full.py without copying game data into the repo.
It reads the stable occurrence index; it never assigns new UIDs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
META = ('uid', 'source_language', 'speaker_language', 'kind', 'sources',
        'source_policy', 'original_source_sha256', 'occurrences',
        'source_provenance')


def text_hash(value):
    return None if value is None else hashlib.sha256(value.encode('utf-8')).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def jsonl_text(rows):
    return ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)


def load_jsonl(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]
    uids = [row['uid'] for row in rows]
    if len(uids) != len(set(uids)):
        raise ValueError('Duplicate UID in ' + str(path))
    return rows


def export_rows(rows, originals, extra_uids):
    result = []
    for row in rows:
        if row['source_language'] not in ('en', 'ja') or row['speaker_language'] not in ('en', 'ja'):
            raise ValueError('Unsupported source language: ' + row['uid'])
        item = {key: row[key] for key in META if key in row}
        disc_hash = text_hash(originals[row['uid']][1])
        if row['uid'] not in extra_uids and disc_hash != row['original_source_sha256']:
            raise ValueError('Decoded original source hash differs: ' + row['uid'])
        # The later encyclopedia additions used their English reference hash
        # in this historical provenance field. Preserve that field verbatim,
        # but pin every public row to a separate, actual disc-body hash.
        provenance_hash_kind = 'corrected_english_reference' if row['uid'] in extra_uids else 'decoded_disc_body'
        item.update(public_schema=SCHEMA, text_sha256=text_hash(row['text']),
                    speaker_sha256=text_hash(row.get('speaker')),
                    disc_body_sha256=disc_hash, original_source_hash_kind=provenance_hash_kind,
                    derive_text_from_disc=row['source_language'] == 'ja',
                    derive_speaker_from_disc=row['speaker_language'] == 'ja' and row.get('speaker') is not None)
        if not item['derive_text_from_disc']:
            item['text'] = row['text']
        if not item['derive_speaker_from_disc']:
            item['speaker'] = row.get('speaker')
        result.append(item)
    return result


def export_sources(args):
    rows = load_jsonl(args.input)
    occurrences = json.loads(args.occurrences.read_text(encoding='utf-8'))
    _, extra, _, originals = decode_disc_inputs(occurrences, args.disc_dir)
    if set(originals) != {row['uid'] for row in rows}:
        raise ValueError('Chosen source and occurrence UID sets differ')
    public = export_rows(rows, originals, {row['uid'] for row in extra})
    summary = {'mode': 'write' if args.write else 'dry_run', 'action': 'export-sources',
               'rows': len(public), 'source_languages': dict(Counter(row['source_language'] for row in public)),
               'disc_derived_texts': sum(row['derive_text_from_disc'] for row in public),
               'disc_derived_speakers': sum(row['derive_speaker_from_disc'] for row in public),
               'output': str(args.output.resolve()), 'sample_uids': [row['uid'] for row in public[:3]]}
    print(json_text(summary), end='', flush=True)
    if not args.write:
        return
    if args.output.exists():
        raise FileExistsError('Refusing to overwrite ' + str(args.output))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=args.output.parent,
                                     prefix='.' + args.output.name, delete=False) as target:
        temporary = Path(target.name)
        target.write(jsonl_text(public))
    try:
        if load_jsonl(temporary) != public:
            raise ValueError('Public source manifest round trip failed')
        if args.output.exists():
            raise FileExistsError(args.output)
        temporary.rename(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json_text({'public_sources_sha256': file_hash(args.output)}), end='')


class DiscStrings:
    """Read original strings using extracted archives, without creating dumps."""
    def __init__(self, disc_dir):
        self.disc_dir = Path(disc_dir)
        self.archives = {}
        self.files = {}

    def entry(self, archive, index):
        if archive not in self.archives:
            data = (self.disc_dir / (archive + '.DAT')).read_bytes()
            count = struct.unpack_from('<H', data)[0]
            if 2 + (count + 1) * 2 > len(data):
                raise ValueError('Invalid DAT header: ' + archive)
            offsets = struct.unpack_from('<%dH' % (count + 1), data, 2)
            if any(a > b for a, b in zip(offsets, offsets[1:])) or offsets[-1] * 2048 > len(data):
                raise ValueError('Invalid DAT offsets: ' + archive)
            self.archives[archive] = (data, offsets)
        data, offsets = self.archives[archive]
        if not 0 <= index < len(offsets) - 1:
            raise ValueError('Missing DAT entry: %s%04d' % (archive, index))
        return data[offsets[index] * 2048:offsets[index + 1] * 2048]

    def buffer(self, name):
        if name not in self.files:
            if name == 'SLPS':
                data = (self.disc_dir / 'SLPS_028.63').read_bytes()
            else:
                match = re.fullmatch(r'([A-Z]+)(\d{4})', name)
                if not match:
                    raise ValueError('Unknown original resource: ' + name)
                data = self.entry(match[1], int(match[2]))
            self.files[name] = data
        return self.files[name]

    def words(self, row):
        data = self.buffer(row['file'])
        offset = row['off']
        expected = int(row['term'], 16)
        if offset < 0 or offset % 2 or expected not in (0xFFFD, 0xFFFE):
            raise ValueError('Invalid occurrence: ' + row['uid'])
        words = []
        for position in range(offset, len(data) - 1, 2):
            word = struct.unpack_from('<H', data, position)[0]
            if word in (0xFFFD, 0xFFFE):
                if word != expected:
                    raise ValueError('Original terminator changed: ' + row['uid'])
                return words
            words.append(word)
        raise ValueError('Missing original terminator: ' + row['uid'])

    def decoder(self):
        # dump_script loads the battle map at import. Supply that native sheet
        # from the user's extracted DAT instead of a machine-local unpack path.
        import numpy as np
        import fontsets
        tim = self.entry('BATTLE', 538)
        position = 8 + struct.unpack_from('<I', tim, 8)[0]
        _, _, _, width, height = struct.unpack_from('<IHHHH', tim, position)
        raw = np.frombuffer(tim[position + 12:position + 12 + width * 2 * height], dtype=np.uint8).reshape(height, width * 2)
        sheet = np.empty((height, width * 4), dtype=np.uint8)
        sheet[:, 0::2] = raw & 15
        sheet[:, 1::2] = raw >> 4
        fontsets._BAT = sheet
        import dump_script
        return dump_script.decode


def decode_disc_inputs(occurrences, disc_dir):
    coordinates = [(row['file'], row['off']) for row in occurrences]
    if len(coordinates) != len(set(coordinates)):
        raise ValueError('Duplicate source coordinates')
    disc = DiscStrings(disc_dir)
    decode = disc.decoder()
    strings, extra, units, unit_map, originals = [], [], [], {}, {}
    for row in occurrences:
        speaker, body = decode(disc.words(row), row['font'], dialogue=row['src'] in ('stage', 'bquote'))
        uid = row['uid']
        if uid in originals and originals[uid] != (speaker, body):
            raise ValueError('Same UID decodes differently: ' + uid)
        originals[uid] = (speaker, body)
        if row.get('extra'):
            extra.append(dict(row))
            continue
        item = dict(row)
        item.update(id='%s:%s:%05X' % (row['src'], row['file'], row['off']),
                    speaker_jp=speaker, jp=body)
        strings.append(item)
        if uid not in unit_map:
            unit = {'uid': uid, 'speaker_jp': speaker, 'jp': body, 'count': 0,
                    'first': item['id'], 'sources': []}
            units.append(unit)
            unit_map[uid] = unit
        unit = unit_map[uid]
        unit['count'] += 1
        if row['src'] not in unit['sources']:
            unit['sources'].append(row['src'])
    return strings, extra, units, originals


def prepare_inputs(args):
    public = load_jsonl(args.sources)
    selected = {row['uid']: row for row in public}
    occurrences = json.loads(args.occurrences.read_text(encoding='utf-8'))
    if {row['uid'] for row in occurrences} != set(selected):
        raise ValueError('Source manifest and occurrence UID sets differ')
    strings, extra, units, originals = decode_disc_inputs(occurrences, args.disc_dir)
    restored = []
    for row in public:
        uid = row['uid']
        if row.get('public_schema') != SCHEMA:
            raise ValueError('Unsupported public source schema: ' + uid)
        speaker, body = originals[uid]
        if text_hash(body) != row['disc_body_sha256']:
            raise ValueError('Decoded disc body hash differs: ' + uid)
        text = body if row['derive_text_from_disc'] else row['text']
        chosen_speaker = speaker if row['derive_speaker_from_disc'] else row.get('speaker')
        if text_hash(text) != row['text_sha256'] or text_hash(chosen_speaker) != row['speaker_sha256']:
            raise ValueError('Chosen source hash differs: ' + uid)
        item = {key: row[key] for key in META if key in row}
        item.update(text=text, speaker=chosen_speaker)
        restored.append(item)
    payloads = {'units.json': json_text(units), 'strings.json': json_text(strings),
                'extra_occurrences.json': json_text(extra),
                'all_units.input.jsonl': jsonl_text(restored)}
    summary = {'mode': 'write' if args.write else 'dry_run', 'action': 'prepare',
               'units': len(units), 'strings': len(strings), 'extra_occurrences': len(extra),
               'chosen_sources': len(restored), 'uid_reassignment': False,
               'original_source_hashes_verified': len(restored),
               'chosen_source_hashes_verified': len(restored),
               'output': str(args.output.resolve()),
               'sources_sha256': file_hash(args.sources),
               'occurrences_sha256': file_hash(args.occurrences),
               'files': {name: {'bytes': len(text.encode('utf-8')),
                                'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
                         for name, text in payloads.items()}}
    print(json_text(summary), end='', flush=True)
    if not args.write:
        return
    if args.output.exists():
        raise FileExistsError('Refusing to overwrite ' + str(args.output))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + args.output.name + '-', dir=args.output.parent))
    try:
        for name, text in payloads.items():
            (staging / name).write_text(text, encoding='utf-8')
            if file_hash(staging / name) != summary['files'][name]['sha256']:
                raise ValueError('Written input hash differs: ' + name)
        (staging / 'prepare_manifest.json').write_text(json_text(summary), encoding='utf-8')
        if args.output.exists():
            raise FileExistsError(args.output)
        staging.rename(args.output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    export = commands.add_parser('export-sources', help='strip private chosen sources into a public JSONL manifest')
    export.add_argument('--input', type=Path, required=True)
    export.add_argument('--occurrences', type=Path, default=ROOT / 'work/script/occurrences.json')
    export.add_argument('--disc-dir', type=Path, default=ROOT / 'work/source/disc')
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--write', action='store_true')
    export.set_defaults(run=export_sources)
    prepare = commands.add_parser('prepare', help='reconstruct private build inputs from the original extracted disc')
    prepare.add_argument('--sources', type=Path, default=ROOT / 'work/translation/zh_CN/public/chosen_sources.jsonl')
    prepare.add_argument('--occurrences', type=Path, default=ROOT / 'work/script/occurrences.json')
    prepare.add_argument('--disc-dir', type=Path, default=ROOT / 'work/source/disc')
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--write', action='store_true')
    prepare.set_defaults(run=prepare_inputs)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()
