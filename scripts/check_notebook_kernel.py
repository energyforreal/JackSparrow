import nbformat
nb = nbformat.read('notebooks/JackSparrow_Training_Colab_v6.ipynb', as_version=4)
print(nb.metadata.get('kernelspec', 'no kernelspec'))
