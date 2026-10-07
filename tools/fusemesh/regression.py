"""Run the unchanged T003 verifier while keeping writes in T005's exclusive root."""
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/erdata/scripts'))
import verify_armor_builder

if __name__=='__main__':
    verify_armor_builder.DATA=ROOT/'er-data/s3/fuse/regression'
    verify_armor_builder.math=math
    verify_armor_builder.main()
