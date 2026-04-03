from pathlib import Path
import re
raw = Path('notebooks/JackSparrow_Training_Colab_v6.ipynb').read_text(encoding='utf-8')
print('len', len(raw))
print('contains marker', '<VSCode.Cell' in raw)
print('first index', raw.find('<VSCode.Cell'))
print('match1', bool(re.search(r'<VSCode\.Cell[^>]*language="python">\r?\n', raw)))
print('closing match', bool(re.search(r'</VSCode\.Cell>', raw)))
print('match all', len(re.findall(r'<VSCode\.Cell[^>]*language="python">\r?\n(.*?)</VSCode\.Cell>', raw, flags=re.S)))
