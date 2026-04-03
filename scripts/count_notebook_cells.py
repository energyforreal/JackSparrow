import nbformat
nb = nbformat.read('notebooks/JackSparrow_Training_Colab_v6.ipynb', as_version=4)
print('cells', len(nb.cells))
print('first cell source lines:', len(nb.cells[0].source.splitlines()))
