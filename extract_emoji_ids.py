from pathlib import Path
import re

source = Path('/home/ubuntu/upload/pasted_content.txt')
output = Path('/home/ubuntu/skx_talha_bot/emoji_pools.py')
ids = []
for value in re.findall(r'ID:\s*(\d+)', source.read_text(encoding='utf-8')):
    if value not in ids:
        ids.append(value)
output.write_text(
    '# Generated from the supplied premium emoji export.\n'
    'PREMIUM_EMOJI_IDS = ' + repr(ids) + '\n',
    encoding='utf-8',
)
print(f'extracted {len(ids)} unique emoji IDs')
