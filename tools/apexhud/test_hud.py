"""T017 integration regressions; run after exporting Octane and fuse_check."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
from PIL import Image
from legend import HUD_ROOT, output_path, load_legend
from verify_hud import verify
from verify_reproduction import file_equal

HERE = Path(__file__).resolve().parent
OCTANE = HUD_ROOT / 'octane'
FUSE = OCTANE / 'fuse_check'


def read(root, name):
    return json.loads((root / name).read_text(encoding='utf8'))


class HudRegression(unittest.TestCase):
    def test_default_and_output_boundary(self):
        self.assertEqual(output_path('fuse'), HUD_ROOT.resolve())
        self.assertEqual(output_path('octane'), OCTANE.resolve())
        for invalid in (HUD_ROOT, HERE, OCTANE / '..' / 'sibling'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                output_path('octane', invalid)

    def test_common_visual_content(self):
        a, b = read(FUSE, 'hud_pack.json'), read(OCTANE, 'hud_pack.json')
        for key in ('canvas', 'coordinate_system', 'scaling', 'font_choice', 'preview_state', 'limitations'):
            self.assertEqual(a[key], b[key], key)
        self.assertEqual([e for e in a['elements'] if e['id'] != 'health'],
                         [e for e in b['elements'] if e['id'] != 'health'])
        general_a = {n: v for n, v in a['images'].items() if 'fuse' not in n}
        general_b = {n: v for n, v in b['images'].items() if 'octane' not in n}
        self.assertEqual(general_a, general_b)
        for name, icon in general_a.items():
            for field in ('image', 'payload_image'):
                self.assertTrue(file_equal(FUSE / icon[field], OCTANE / general_b[name][field]), (name, field))
        for filename in ('palette.json', 'rui/summary.json', 'extra_images.json', 'extra_localization.json'):
            self.assertTrue(file_equal(FUSE / filename, OCTANE / filename), filename)
        for entry in read(FUSE, 'extra_images.json').values():
            self.assertTrue(file_equal(FUSE / entry['payload_image'], OCTANE / entry['payload_image']))
        print(f'Common content: {len(general_a)} main images + 11 supplemental images, 6 HUD elements')

    def test_fonts_preserve_base_characters(self):
        a, b = read(FUSE, 'fonts/fonts.json')['fonts'], read(OCTANE, 'fonts/fonts.json')['fonts']
        base_glyphs, additional_glyphs = 0, 0
        self.assertEqual(len(a), len(b))
        for first, second in zip(a, b):
            self.assertEqual(first['guid'], second['guid'])
            for field in ('atlas_png', 'atlas_dds', 'metadata'):
                self.assertTrue(file_equal(FUSE / first[field], OCTANE / second[field]), field)
            for p, q in zip(first['profiles'], second['profiles']):
                self.assertEqual({k: v for k, v in p.items() if k != 'glyphs'},
                                 {k: v for k, v in q.items() if k != 'glyphs'})
                self.assertTrue(p['glyphs'].keys() <= q['glyphs'].keys())
                for cp, glyph in p['glyphs'].items():
                    self.assertEqual(glyph, q['glyphs'][cp])
                    self.assertTrue(file_equal(FUSE / glyph['image'], OCTANE / glyph['image']))
                base_glyphs += len(p['glyphs'])
                additional_glyphs += len(q['glyphs']) - len(p['glyphs'])
        print(f'Fonts: {base_glyphs} original glyphs preserved, {additional_glyphs} added')

    def test_pack_cli_is_stable(self):
        before = (OCTANE / 'hud_pack.json').read_bytes()
        result = subprocess.run([sys.executable, '-B', str(HERE / 'pack.py'), '--legend', 'octane'],
                                cwd=HERE, capture_output=True, text=True, encoding='utf8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, (OCTANE / 'hud_pack.json').read_bytes())

    def test_corrupt_valid_png_is_rejected(self):
        info = load_legend(OCTANE, 'octane')
        asset = next(a for a in read(OCTANE, 'assets.json')['assets'] if a.get('image'))
        # Minimal source fixture reaches the content check before other assets.
        # The temporary path is validated before context cleanup can delete it.
        with tempfile.TemporaryDirectory(prefix='_verify_test_', dir=OCTANE) as directory:
            fixture = Path(directory).resolve()
            self.assertTrue(fixture.is_relative_to(OCTANE.resolve()))
            paths = {'hud_pack.json', 'fonts/fonts.json', info['source'],
                     asset['image'], asset['payload_image'], asset['metadata']}
            paths.update(a['source'] for a in info['abilities'].values())
            paths.update(a['source'] for a in info['upgrades'])
            raw_png = asset['metadata'].removesuffix('.meta.json') + '.png'
            paths.add(raw_png)
            for name in paths:
                target = fixture / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(OCTANE / name, target)
            (fixture / 'assets.json').write_text(json.dumps({'assets': [asset]}), encoding='utf8')
            target = fixture / asset['image']
            with Image.open(target) as source:
                im = source.convert('RGBA')
            x, y = asset['content_rect'][:2]
            r, g, b, alpha = im.getpixel((x, y))
            im.putpixel((x, y), (r ^ 1, g, b, alpha))
            im.save(target)
            with self.assertRaisesRegex(AssertionError, 'Logical canvas differs from payload'):
                verify(fixture, 'octane')


if __name__ == '__main__':
    unittest.main(verbosity=2)
