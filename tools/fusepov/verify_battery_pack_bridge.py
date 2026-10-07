"""Import the pack verifier without colliding with the model verifier's module name."""
import importlib.util
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from common import ROOT

spec = importlib.util.spec_from_file_location('battery_pack_verifier',ROOT/'tools/apexpov/verify_battery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def verify_pack_input(out):
    return module.verify(out,write_report=False,pack_path=out/'inputs/fuse_pov.anim',sequence_path=out/'inputs/battery_sequences.json')
