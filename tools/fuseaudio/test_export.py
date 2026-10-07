"""Synthetic parser checks; live bank/WAV checks are part of export_audio.py."""
import sys

sys.dont_write_bytecode = True

import unittest
from pathlib import Path
import struct
import tempfile

from miles import lzb_decode
from export_audio import FRAG_OUT, OCTANE_OUT, OUT, output_directory, read_wave, write_wave
from compare_r301 import same_content, without_hash_fields
import numpy as np


class ParserTests(unittest.TestCase):
    def test_lzb_overlap_and_final_literals(self):
        encoded = bytes([0xf1]) + b'a' + bytes([0xf9, 1, 9]) + b'bcdefghij'
        self.assertEqual(lzb_decode(encoded, 30), b'a' * 21 + b'bcdefghij')
        false_nine = bytes([0xf1]) + b'a' + bytes([0xf9, 1, 9]) + b'bcdef'
        self.assertEqual(lzb_decode(false_nine, 26), b'a' * 21 + b'bcdef')

    def test_lzb_rejects_bad_back_reference(self):
        with self.assertRaises(ValueError):
            lzb_decode(bytes([0, 0, 0]), 20)

    def test_wave_validation(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='test_wav_') as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(Path(__file__).parent.resolve()))
            path = Path(folder) / 'synthetic.wav'
            write_wave(path, np.array([[0.25, -0.25], [0, 0]], dtype=np.float32), 48000)
            samples, info = read_wave(path)
            self.assertEqual(samples.shape, (2, 2))
            self.assertEqual(info['frames'], 2)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                read_wave(path)
            write_wave(path, np.array([[float('nan'), 0]], dtype=np.float32), 48000)
            with self.assertRaises(ValueError):
                read_wave(path)
            path.write_bytes(b'RIFF')
            with self.assertRaises(ValueError):
                read_wave(path)

    def test_wave_loop_data_and_bounds(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='test_loop_') as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(Path(__file__).parent.resolve()))
            path = Path(folder) / 'loop.wav'
            write_wave(path, np.ones((4, 2), dtype=np.float32) * 0.25, 48000)
            original = path.read_bytes()
            for end, valid in [(3, True), (4, False)]:
                sampler = struct.pack('<9I', 0, 0, 0, 60, 0, 0, 0, 1, 0)
                sampler += struct.pack('<6I', 7, 0, 1, end, 0, 0)
                body = original[8:] + b'smpl' + struct.pack('<I', len(sampler)) + sampler
                path.write_bytes(b'RIFF' + struct.pack('<I', len(body)) + body)
                if valid:
                    _, info = read_wave(path, include_loop_data=True)
                    self.assertEqual(info['wav_loop_data']['loops'][0],
                                     {'id': 7, 'type': 0, 'start_frame': 1, 'end_frame_inclusive': 3,
                                      'fraction': 0, 'play_count': 0})
                else:
                    with self.assertRaises(ValueError):
                        read_wave(path, include_loop_data=True)

    def test_output_defaults_and_octane_boundary(self):
        self.assertEqual(output_directory('r301'), OUT.resolve())
        self.assertEqual(output_directory('octane'), OCTANE_OUT.resolve())
        self.assertEqual(output_directory('r301', OCTANE_OUT / 'r301_check'),
                         (OCTANE_OUT / 'r301_check').resolve())
        with self.assertRaises(ValueError):
            output_directory('octane', OUT)

    def test_frag_boundary(self):
        # U9: the frag grenade's set writes only inside audio/frag_grenade/
        self.assertEqual(output_directory('frag'), FRAG_OUT.resolve())
        self.assertEqual(output_directory('frag', FRAG_OUT / 'check'), (FRAG_OUT / 'check').resolve())
        with self.assertRaises(ValueError):
            output_directory('frag', OCTANE_OUT)

    def test_direct_comparison_detects_same_size_changes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='test_compare_') as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(Path(__file__).parent.resolve()))
            left, right = Path(folder) / 'left', Path(folder) / 'right'
            left.write_bytes(b'abcd')
            right.write_bytes(b'abcd')
            self.assertTrue(same_content(left, right))
            right.write_bytes(b'abce')
            self.assertFalse(same_content(left, right))
            right.write_bytes(b'abc')
            self.assertFalse(same_content(left, right))
        self.assertEqual(without_hash_fields({'raw': {'bytes': 4, 'sha256': 'old'}}), {'raw': {'bytes': 4}})
        self.assertNotEqual(without_hash_fields({'frames': 4}), without_hash_fields({'frames': 5}))


if __name__ == '__main__':
    unittest.main()
