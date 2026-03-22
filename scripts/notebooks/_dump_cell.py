import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
nb = json.loads((_ROOT / "notebooks" / "JackSparrow_Trading_Colab_v5.ipynb").read_text(encoding="utf-8"))
(_ROOT / "_cell27.txt").write_text("".join(nb["cells"][27]["source"]), encoding="utf-8")
