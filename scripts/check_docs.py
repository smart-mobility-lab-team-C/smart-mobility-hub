#!/usr/bin/env python3
"""Check repository-local Markdown link targets without fetching external links."""
from pathlib import Path
import re
import sys
from urllib.parse import unquote

root = Path(__file__).resolve().parents[1]
failures = []
for path in [root / 'README.md', root / 'AGENTS.md', root / 'CONTRIBUTING.md',
             *sorted((root / 'docs').glob('*.md'))]:
    for target in re.findall(r'\]\(([^\s)]+)\)', path.read_text()):
        if '://' in target or target.startswith(('#', 'mailto:')):
            continue
        local = unquote(target.split('#', 1)[0])
        if not (path.parent / local).exists():
            failures.append(f'{path.relative_to(root)}: missing {target}')
print('\n'.join(failures) if failures else 'PASS: local Markdown link targets')
sys.exit(bool(failures))
