import nbformat
nb = nbformat.read("notebooks/jacksparrow_delta_india_training.ipynb", as_version=4)
print('cells', len(nb.cells))
print('first cell source lines:', len(nb.cells[0].source.splitlines()))
