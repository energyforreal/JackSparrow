import json
from pathlib import Path

nb = json.loads(Path("notebooks/JackSparrow_Trading_Colab_v5.ipynb").read_text(encoding="utf-8"))
Path("_cell27.txt").write_text("".join(nb["cells"][27]["source"]), encoding="utf-8")
