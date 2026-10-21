#!/usr/bin/env python3
"""Prepare a Chinese source checkout using a user's original Japanese BIN.

Read-only by default. --write stages licensed fonts and atomically creates
work/source with the original extracted files, unpacked archives and verified
Chinese build inputs. The original BIN is never copied or opened for writes.
No downloads, account access, game build or publication is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_BYTES = 725316816
ORIGINAL_SHA256 = '219d9c4f64caf670b5e400612fa19677ed9a3f59a7ebdb72c12c425412795465'
ARCHIVES = ('BATTLE', 'EVENT', 'MAPMAIN', 'STAGE')
FONTS = {
    'Cubic11/Cubic_11.ttf': '0193f5f033612496df6b45ee92ac3b335bc6a5a24ff95da55ca87b33e57dcf62',
    'Cubic11/OFL.txt': '2b6e5938e5cffa0b9e183bd05f8c363e174e7ebed1a0556e2855fd1707fa2188',
    'Misaki/misaki.txt': '82929cc3b34c79b6a67f21fe137c7bb165589c9e34ba1441611e493afd67dfca',
    'Misaki/misaki_gothic.ttf': '0963e11e89d5fa409a7a048a52e8ea2d623d764a7998488f8a4291111611c4e1',
    'Misaki/readme.txt': '50419b4ecefd8cf946b9a1666ebcba708a38feea48aa6d0643ee8d0a3ede430c',
    'Misaki/source.json': '89c9fe93c7b08aa8b41da8a6ed467ac2e1a7572cac09bf01cef2a9e6ef4bd954',
}


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def dependencies():
    try:
        import numpy
        import PIL
        from PIL import features
    except ImportError as error:
        raise RuntimeError('Install the core dependencies with: python -m pip install numpy pillow') from error
    return {'python': sys.version.split()[0], 'numpy': numpy.__version__,
            'pillow': PIL.__version__, 'freetype': features.version_module('freetype2')}


def validate_fonts(workspace):
    report = []
    for relative, expected in FONTS.items():
        source = ROOT / 'assets/fonts' / relative
        if not source.is_file() or digest(source) != expected:
            raise ValueError('Bundled font or notice differs: ' + relative)
        destination = workspace / 'incoming' / relative
        exists = destination.exists()
        if exists and (not destination.is_file() or digest(destination) != expected):
            raise FileExistsError('Refusing to replace a different existing font/notice: ' + str(destination))
        report.append({'path': relative, 'sha256': expected,
                       'action': 'keep_matching' if exists else 'copy'})
    return report


def stage_fonts(workspace):
    for relative, expected in FONTS.items():
        source = ROOT / 'assets/fonts' / relative
        destination = workspace / 'incoming' / relative
        if destination.exists():
            if digest(destination) != expected:
                raise FileExistsError('Font changed during setup: ' + str(destination))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.' + destination.name,
                                         delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(source, temporary)
            if digest(temporary) != expected:
                raise ValueError('Font copy failed: ' + relative)
            if destination.exists():
                raise FileExistsError(destination)
            temporary.rename(destination)
        finally:
            temporary.unlink(missing_ok=True)


def command(script, *arguments):
    return [sys.executable, '-B', str(ROOT / 'tools' / script), *map(str, arguments)]


def run_step(name, argv, logs):
    print('Running ' + name + '...', flush=True)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    log = logs / (name + '.log')
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        print(result.stdout[-2500:] + result.stderr[-2500:], file=sys.stderr, flush=True)
        raise RuntimeError('%s failed (exit %d); %s' % (name, result.returncode, log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-bin', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, default=ROOT,
                        help='checkout to prepare; use a separate directory for an isolated bootstrap check')
    parser.add_argument('--sources', type=Path,
                        default=ROOT / 'work/translation/zh_CN/chosen_sources.public.jsonl')
    parser.add_argument('--occurrences', type=Path, default=ROOT / 'work/script/occurrences.json')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    original = args.source_bin.resolve(strict=True)
    workspace = args.workspace.resolve()
    destination = workspace / 'work/source'
    if original.stat().st_size != ORIGINAL_BYTES or digest(original) != ORIGINAL_SHA256:
        raise ValueError('The source must be the original SLPS-02863 single-track MODE2/2352 BIN with SHA-256 ' + ORIGINAL_SHA256)
    versions = dependencies()
    fonts = validate_fonts(workspace)
    for path in (args.sources, args.occurrences, ROOT / 'tools/extract_iso.py',
                 ROOT / 'tools/dat_archive.py', ROOT / 'tools/prepare_zh_public_inputs.py'):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = {'mode': 'write' if args.write else 'dry_run', 'source_bin': str(original),
            'source_bytes': ORIGINAL_BYTES, 'source_sha256': ORIGINAL_SHA256,
            'source_opened_read_only': True, 'workspace': str(workspace),
            'private_data_directory': str(destination), 'existing_source_directory': destination.exists(),
            'sources_manifest': str(args.sources.resolve()), 'sources_sha256': digest(args.sources),
            'occurrences_sha256': digest(args.occurrences), 'dependencies': versions,
            'licensed_font_files': fonts,
            'steps': ['extract original disc with tools/extract_iso.py',
                      'unpack BATTLE/EVENT/MAPMAIN/STAGE with tools/dat_archive.py',
                      'reconstruct local work/source/zh_inputs with tools/prepare_zh_public_inputs.py',
                      'copy licensed fonts from assets/fonts to incoming'],
            'output_overwrite_allowed': False}
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.write:
        return
    if destination.exists():
        raise FileExistsError('Refusing to overwrite existing private source data: ' + str(destination))
    (workspace / 'work').mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.zh-source-', dir=workspace / 'work'))
    logs = staging / 'setup_logs'
    logs.mkdir()
    try:
        run_step('extract_disc', command('extract_iso.py', original, staging / 'disc'), logs)
        for archive in ARCHIVES:
            run_step('unpack_' + archive.lower(), command('dat_archive.py', staging / 'disc' / (archive + '.DAT'),
                                                        staging / 'unpacked'), logs)
        prepare = command('prepare_zh_public_inputs.py', 'prepare', '--sources', args.sources.resolve(),
                          '--occurrences', args.occurrences.resolve(), '--disc-dir', staging / 'disc',
                          '--output', staging / 'zh_inputs')
        run_step('prepare_inputs_plan', prepare, logs)
        run_step('prepare_inputs_write', prepare + ['--write'], logs)
        if digest(original) != ORIGINAL_SHA256:
            raise ValueError('Original source changed while setup was running')
        stage_fonts(workspace)
        input_manifest_path = staging / 'zh_inputs/prepare_manifest.json'
        input_manifest = json.loads(input_manifest_path.read_text(encoding='utf-8'))
        input_manifest['output'] = str(destination / 'zh_inputs')
        write_json(input_manifest_path, input_manifest)
        plan.update(status='prepared', original_sha256_after=ORIGINAL_SHA256,
                    private_input_manifest=input_manifest)
        write_json(staging / 'setup_manifest.json', plan)
        if destination.exists():
            raise FileExistsError(destination)
        staging.rename(destination)
    except Exception:
        # Keep diagnostics locally on failure; never reuse partial extraction
        # as a successful setup or move it over existing source data.
        print('Incomplete setup retained for diagnostics: ' + str(staging), file=sys.stderr)
        raise
    print(json.dumps({'status': 'prepared', 'source_sha256': ORIGINAL_SHA256,
                      'private_data_directory': str(destination),
                      'inputs': str(destination / 'zh_inputs'),
                      'manifest': str(destination / 'setup_manifest.json')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
