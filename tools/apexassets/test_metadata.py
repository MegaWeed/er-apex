"""Regression checks for real QC forms used by the Octane jump pad."""
import tempfile
import unittest
from pathlib import Path

from inspect_assets import qc_sections


class QcMetadataTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.qc'
            path.write_text(text, encoding='utf-8')
            return qc_sections(path)[1]

    def test_brace_free_sequences_and_loop_are_preserved(self):
        text = ('$sequence "card" "card_animation"\n'
                '$sequence "deploy_idle" "idle_animation" loop\n'
                '$sequence "deploy" "deploy_animation" {\n activity "ACT_VM_DEPLOY" 1\n}\n')
        sections = self.parse(text)
        self.assertEqual([s[1] for s in sections], ['card', 'deploy_idle', 'deploy'])
        self.assertIn(' loop', sections[1][2])
        self.assertNotIn('$sequence "deploy"', sections[1][2])
        self.assertIn('ACT_VM_DEPLOY', sections[2][2])

    def test_nested_blocks_and_quoted_braces(self):
        sections = self.parse('$sequence "idle" "idle" {\n event 1 0 "a{b}"\n { nested }\n}\n')
        self.assertEqual(len(sections), 1)
        self.assertTrue(sections[0][2].endswith('}'))

    def test_unclosed_block_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse('$sequence "idle" "idle" {\n')


if __name__ == '__main__':
    unittest.main()
