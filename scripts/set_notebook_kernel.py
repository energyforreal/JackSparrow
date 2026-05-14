import nbformat
from pathlib import Path

p = Path("notebooks/jacksparrow_delta_india_training.ipynb")
nb = nbformat.read(p, as_version=4)
nb.metadata['kernelspec'] = {
    'name': 'python3',
    'display_name': 'Python 3',
    'language': 'python'
}
nbformat.write(nb, p)
print('set kernelspec to python3')
