# Quick Start: Google Colab Training

Copy-paste this into a Colab notebook cell:

## Cell 1: Install Dependencies
```python
!pip install -q xgboost ta-lib pandas numpy requests scikit-learn tqdm
```

## Cell 2: Mount Google Drive
```python
from google.colab import drive
drive.mount('/content/drive', force_remount=True)
```

## Cell 3: Navigate & Run Training (20,000 candles)
```bash
cd /content/drive/MyDrive/"Trading Agent 2"
!TRAIN_CANDLES=20000 python scripts/train_xgboost_colab.py
```

## Cell 4: Run Training (50,000 candles - RECOMMENDED)
```bash
!TRAIN_CANDLES=50000 python scripts/train_xgboost_colab.py
```

## Cell 5: Check Results
```python
import pandas as pd
from pathlib import Path

summary_path = Path("/content/drive/MyDrive/Trading Agent 2/agent/model_storage/xgboost/training_summary.csv")
df_summary = pd.read_csv(summary_path)
print(df_summary.to_string())
```

---

## Performance Benchmarks (Google Colab GPU)

| Config | Fetch Time | Train Time | Total |
|--------|-----------|-----------|-------|
| 20,000 candles | 2-3 min | 2 min | **5 min** |
| 50,000 candles | 4-6 min | 4 min | **10 min** |
| 100,000 candles | 8-12 min | 8 min | **20 min** |

---

## Advanced Options

### Use More Data (Better Signals!)
```bash
!TRAIN_CANDLES=50000 TRAIN_BATCH_SIZE=1000 python scripts/train_xgboost_colab.py
```

### Train Different Symbol
```bash
!TRAIN_CANDLES=50000 TRAIN_SYMBOL=ETHUSD python scripts/train_xgboost_colab.py
```

### Disable GPU (If Errors)
```bash
!TRAIN_CANDLES=50000 TRAIN_NO_GPU=1 python scripts/train_xgboost_colab.py
```

---

Key Changes from Original:
✅ **20,000+ candles** (was 3,000)
✅ **GPU support** (CUDA acceleration)
✅ **Progress bars** (tqdm)
✅ **Data validation** (gap detection)
✅ **Class distribution** (label analysis)
✅ **Colab path handling** (auto-detect)
