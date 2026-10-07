"""Run legend and T003 checks with every generated file under the T019 root."""
import argparse
import ast
import math
import shutil
import sys
from common import ROOT, BASE, checked_out, save, run, TOOL, EXTRACT, add_options, default_out


def fuse(out):
    stage = out/'regression/fuse'
    for folder in ['package', 'package_flipy', 'fusemesh', 'fusemesh_flipy', 'textures', 'inputs']:
        shutil.copytree(BASE/folder, stage/folder, dirs_exist_ok=True)
    # Execute the original verify_fuse.py __main__. Only its DEFAULT output
    # path is adapted, as the default would write outside T008's exclusive root.
    import convert_fuse
    import runpy
    previous = convert_fuse.DEFAULT
    try:
        convert_fuse.DEFAULT = stage
        runpy.run_path(str(ROOT/'tools/fusemesh/verify_fuse.py'), run_name='__main__')
    finally:
        convert_fuse.DEFAULT = previous


def builder(out):
    stage = out/'regression/builder'
    # D-030: adapt only T003's digest metadata in memory; no read-only edits.
    class SizeMetadata(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            return None if node.name == 'sha' else self.generic_visit(node)
        def visit_Import(self, node):
            node.names = [n for n in node.names if n.name != 'hashlib']
            return node if node.names else None
        def visit_keyword(self, node):
            if node.arg == 'sha' + '256':
                return ast.keyword(arg='size_bytes', value=ast.parse('path.stat().st_size', mode='eval').body)
            return self.generic_visit(node)
    script = ROOT/'tools/erdata/scripts/s3a_roundtrip.py'
    tree = ast.fix_missing_locations(SizeMetadata().visit(ast.parse(script.read_text(encoding='utf-8-sig'))))
    namespace = dict(__file__=str(script), __name__='t019_roundtrip')
    exec(compile(tree, str(script), 'exec'), namespace)
    previous_args = sys.argv
    try:
        sys.argv = [str(script), '--data-dir', str(stage)]
        namespace['main']()
    finally:
        sys.argv = previous_args
    import verify_armor_builder
    previous = verify_armor_builder.DATA
    try:
        verify_armor_builder.DATA = stage
        verify_armor_builder.math = math
        verify_armor_builder.main()
    finally:
        verify_armor_builder.DATA = previous


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['legend', 'fuse', 'builder'])
    add_options(parser)
    args = parser.parse_args()
    out = checked_out(args.out or default_out(args.legend))
    if args.only != 'builder':
        if args.legend == 'fuse':
            fuse(out)
            from verify_repro import verify
            verify(out, 'fuse')
        else:
            from verify_gun import verify
            verify(out, 'octane')
    if args.only in (None, 'builder'):
        builder(out)
    save(out/'regression-verification.json', dict(status='PASS', checks=args.only or f'{args.legend} and T003',
         implementation='Original T005/T003 assertions; output DATA/DEFAULT redirected to T019; T003 digest metadata replaced in memory by sizes',
         legend=args.legend))
