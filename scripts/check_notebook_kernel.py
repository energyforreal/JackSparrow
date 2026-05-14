import nbformat
nb = nbformat.read("notebooks/jacksparrow_delta_india_training.ipynb", as_version=4)
print(nb.metadata.get('kernelspec', 'no kernelspec'))
