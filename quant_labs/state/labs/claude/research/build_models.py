"""Assemble self-contained model.py files: body + inlined shared helpers (the restricted host allows no lab imports)."""
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
helpers = (LAB / 'research/model_helpers.py.txt').read_text(encoding='utf-8')
for key in sys.argv[1:]:
    body = (LAB / 'research/bodies' / f'{key}.py.txt').read_text(encoding='utf-8')
    (LAB / 'strategies' / key / 'model.py').write_text(body.replace('@@HELPERS@@', helpers), encoding='utf-8')
    print('built', key)
