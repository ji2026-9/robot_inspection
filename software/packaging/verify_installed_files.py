import sys
from pathlib import Path

source = Path(__file__).resolve().parent/'payload'
target = Path(sys.argv[1])
expected = []
for path in source.rglob('*'):
    if not path.is_file():
        continue
    relative = path.relative_to(source)
    if any(part in ('include','__pycache__','packaging_test_output') for part in relative.parts):
        continue
    if path.suffix in ('.pyc','.obj') or path.name == '.inspection_gui.lock':
        continue
    expected.append(relative)
missing = [str(path) for path in expected if not (target/path).is_file()]
assert not missing, missing[:20]
print('Verified all installed files:',len(expected))
