"""Verify cached-feature provenance and the saved experiment's immutable inputs."""
import argparse
import hashlib
import json
from pathlib import Path

from .benchmark import write_json


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(cache_metadata, results):
    metadata = json.loads(cache_metadata.read_text())
    checks = {}

    def check(name, actual, expected):
        if actual != expected:
            raise ValueError(f'Provenance mismatch: {name}')
        checks[name] = True

    for name, entry in metadata['inputs'].items():
        check(f'cache_input:{name}', sha(entry['path']), entry['sha256'])
    check('cache_output', sha(metadata['output']['path']), metadata['output']['sha256'])
    for horizon in (30, 60):
        folder = results / f'classification_{horizon}'
        protocol = json.loads((folder / 'protocol.json').read_text())
        run = json.loads((folder / 'results.json').read_text())
        selection = json.loads((folder / 'selection.json').read_text())
        check(f'{horizon}:protocol', run['protocol'], protocol)
        check(f'{horizon}:selection', run['selection'], selection)
        check(f'{horizon}:source', protocol['source_sha256'], metadata['inputs']['source_zip']['sha256'])
        check(f'{horizon}:snapshots', protocol['snapshots_sha256'], metadata['inputs']['snapshots']['sha256'])
        check(f'{horizon}:additional', protocol['additional_sha256'], metadata['output']['sha256'])
        check(f'{horizon}:plan', sha('docs/synchrony_improvement_plan.md'), protocol['plan_sha256'])
        for name, digest in protocol['code_sha256'].items():
            check(f'{horizon}:code:{name}', sha(Path(__file__).with_name(name)), digest)
        for name, summary in run['evaluation'].items():
            check(f'{horizon}:model:{name}', sha(folder / f'{name}.joblib'), summary['artifact_sha256'])
    return {'passed': True, 'checks': checks,
            'scope': 'Input, feature-generation code, experiment code, plan, selection and frozen artifact hashes; not an independent test of model accuracy.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-metadata', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    audit = verify(args.cache_metadata, args.results)
    write_json(args.results / 'provenance_audit.json', audit)
    print('PASS', len(audit['checks']), 'provenance checks', flush=True)


if __name__ == '__main__':
    main()
