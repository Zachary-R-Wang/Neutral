"""Train the learned self-presentation detector on top of Laya.

Run where Laya and scikit-learn are installed (they are not dependencies of Neutral):

    python tools/train_self_presentation.py

Reads datasets/relevance/v1/train_self_presentation.yaml, turns each sentence into numbers
with Laya's encoder, fits a logistic regression, and chooses the cut-off from the training
data alone: the lowest one at which, cross-validated over five different splits, the
detector is right at least 95% of the time it says "remove". Deleting part of the task is
worse than leaving a boast in, so the cut-off trades catching for being right.

Writes src/neutral/data/self_presentation_probe.json. The broad test set is never read.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import yaml
from laya import load
from laya.shortlist import embed_fn_from_agent
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parent.parent
TRAIN = ROOT / "datasets" / "relevance" / "v1" / "train_self_presentation.yaml"
OUT = ROOT / "src" / "neutral" / "data" / "self_presentation_probe.json"
MODEL = "convaiinnovations/laya"
MAX_LENGTH = 128
PRECISION = 0.95


def main() -> None:
    raw = TRAIN.read_bytes()
    data = yaml.safe_load(raw)
    texts = data["positive"] + data["negative"]
    y = np.array([1] * len(data["positive"]) + [0] * len(data["negative"]))

    embed = embed_fn_from_agent(load(MODEL), max_length=MAX_LENGTH)
    X = normalize(embed(texts))

    runs = []
    for seed in range(5):
        cv = StratifiedKFold(5, shuffle=True, random_state=seed)
        clf = LogisticRegression(C=4.0, max_iter=5000)
        runs.append(cross_val_predict(clf, X, y, cv=cv, method="predict_proba")[:, 1])
    p = np.mean(runs, axis=0)

    threshold = precision = recall = None
    for t in np.arange(0.5, 0.96, 0.01):
        flagged = p >= t
        if not flagged.any():
            break
        if (y[flagged] == 1).mean() >= PRECISION:
            threshold = round(float(t), 2)
            precision = float((y[flagged] == 1).mean())
            recall = float(flagged[y == 1].mean())
            break
    if threshold is None:
        raise SystemExit(
            f"No cut-off reaches {PRECISION:.0%} precision on the training data. Add examples "
            f"to {TRAIN.name} before training again; nothing was written."
        )

    clf = LogisticRegression(C=4.0, max_iter=5000).fit(X, y)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "model": MODEL,
                "max_length": MAX_LENGTH,
                "threshold": threshold,
                "cross_validated_precision": round(precision, 3),
                "cross_validated_recall": round(recall, 3),
                "trained_on": TRAIN.name,
                "trained_on_sha256": hashlib.sha256(raw).hexdigest(),
                "trained": date.today().isoformat(),
                "intercept": float(clf.intercept_[0]),
                "coef": [round(float(c), 6) for c in clf.coef_[0]],
            }
        )
    )
    print(
        f"Cut-off {threshold}: right {precision:.0%} of the time it says remove, catches "
        f"{recall:.0%} of self-presentation (training data, cross-validated). "
        f"Written to {OUT.relative_to(ROOT)}."
    )


if __name__ == "__main__":
    main()
