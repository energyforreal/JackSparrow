from pathlib import Path
import nbformat
import re

in_path = Path('notebooks/JackSparrow_Training_Colab_v6.ipynb')
raw_text = in_path.read_text(encoding='utf-8')
cell_matches = re.findall(r'<VSCode\.Cell[^>]*language="python">\n(.*?)</VSCode\.Cell>', raw_text, flags=re.S)
if not cell_matches:
    raise SystemExit('no cells found')

nb = nbformat.v4.new_notebook()
for src in cell_matches:
    nb['cells'].append(nbformat.v4.new_code_cell(src.strip()))

in_path.write_text(nbformat.writes(nb), encoding='utf-8')
print('Notebook JSON saved with', len(nb['cells']), 'cells')
