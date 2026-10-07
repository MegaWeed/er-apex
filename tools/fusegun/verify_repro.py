"""Direct-byte reproduction checks, including read-only T008 Fuse regression."""
import argparse
from pathlib import Path
from common import OUT, FUSE_REFERENCE, default_out, add_options, checked_out, read, save


def verify(repro, legend='fuse', reference=None, report_out=None):
    repro = checked_out(repro)
    reference = Path(reference or (FUSE_REFERENCE if legend == 'fuse' else OUT)).resolve()
    report_out = checked_out(report_out or default_out(legend))
    result = dict(status='PASS', legend=legend, reconstructed_at=str(repro), reference=str(reference), folders={})
    for folder in ['fusemesh', 'textures', 'preview']:
        files = [p.relative_to(reference/folder) for p in (reference/folder).rglob('*') if p.is_file()]
        others = [p.relative_to(repro/folder) for p in (repro/folder).rglob('*') if p.is_file()]
        assert set(files) == set(others), folder
        for relative in files:
            assert (reference/folder/relative).read_bytes() == (repro/folder/relative).read_bytes(), (folder, relative)
        result['folders'][folder] = dict(files=len(files), byte_identical=True)
    packages = {}
    paths = [p.relative_to(reference/'package') for p in (reference/'package').rglob('*.dcx')]
    others = [p.relative_to(repro/'package') for p in (repro/'package').rglob('*.dcx')]
    assert set(paths) == set(others), 'Package file set differs'
    for relative in paths:
        path = reference/'package'/relative
        other = repro/'package'/relative
        assert path.read_bytes() == other.read_bytes(), path.name
        packages[path.name] = dict(size_bytes=path.stat().st_size, byte_identical=True, format='KRAK DCX')
    assert len(packages) == 9
    result['packages'] = packages
    legacy = reference == FUSE_REFERENCE.resolve()
    metadata_changes = []
    for name in ['grip.json', 'bodygroups.json', 'texture-audit.json', 'geometry-summary.json', 'preview-verification.json']:
        if legacy and name == 'grip.json':
            original, rebuilt = read(reference/name), read(repro/name)
            removed = {k for k in original if k.endswith('_' + 'sha' + '256')}
            added = {'legend', 'grip_source', 'provenance_rule', 'source_files'}
            metadata_changes.extend(sorted(removed | added))
            assert {k:v for k,v in original.items() if k not in removed} == {k:v for k,v in rebuilt.items() if k not in added}, name
        else:
            assert (reference/name).read_bytes() == (repro/name).read_bytes(), name
    result['audits_byte_identical'] = not legacy
    result['legacy_audit_metadata_changes'] = metadata_changes
    result['legacy_change_reason'] = 'Digest fields replaced by source paths/sizes and explicit legend provenance; all legacy grip values unchanged' if legacy else None
    save(report_out/'reproducibility.json', result)
    print('PASS direct reproduction: 9 DCX packages, all fusemesh/texture/preview files; audits exact except recorded legacy provenance metadata', flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_options(parser)
    parser.add_argument('--repro', type=Path)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    out = args.out or default_out(args.legend)
    verify(args.repro or (out if args.legend == 'fuse' else out/'repro'), args.legend,
           args.reference, out)
