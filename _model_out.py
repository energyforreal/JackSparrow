from pathlib import Path
import re

# contract fusion outputs
c = Path("feature_store/transformer_btcusd/contract.py").read_text(encoding="utf-8")
for pat in ["ONNX_OUTPUT_NAMES_V10", "FUSION_HORIZON_KEYS", "FUSION_DIR_COLS", "FUSION_DIRECTION_NAMES", "FUSION_GRADE", "FUSION_ONNX"]:
    for i,l in enumerate(c.splitlines(),1):
        if pat in l and (l.strip().startswith(pat) or l.strip().startswith("ONNX") or "FUSION_HORIZON" in l[:40] or "FUSION_DIR" in l[:30] or "FUSION_DIRECTION_NAMES" in l or "FUSION_GRADE" in l or "FUSION_ONNX" in l):
            print(f"{i:4d}|{l}")

print("\n===== model forward/heads =====")
m = Path("scripts/colab/mtf_fusion_model.py").read_text(encoding="utf-8")
# print class and forward
text = m
idx = text.find("class MtfFusionTransformer")
print(text[idx:idx+4500])
