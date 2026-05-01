"""Train-median feature engineer parity."""

import numpy as np
import pandas as pd

from feature_store.jacksparrow_feature_engineer import JackSparrowTrainMedianEngineer


def test_fit_transform_imputation() -> None:
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "a": rng.normal(size=100),
            "b": rng.normal(size=100),
            "c": rng.normal(size=100),
        }
    )
    df.loc[0:5, "a"] = np.nan
    cols = ["a", "b", "c"]
    eng = JackSparrowTrainMedianEngineer()
    eng.fit(df, cols)
    out = eng.transform(df.iloc[10:20])
    assert not out.isna().any().any()
