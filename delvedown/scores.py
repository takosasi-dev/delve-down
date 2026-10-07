"""ハイスコア(上位10件)の読み書き。"""

from __future__ import annotations

import json
import os
from pathlib import Path

KEEP = 10


class ScoreFileError(Exception):
    """スコアファイルが壊れていて読めない。上書きして消さないために分けている。"""


def default_path(env=os.environ) -> Path:
    base = env.get("XDG_DATA_HOME", "")
    if not os.path.isabs(base):  # XDG の決まりで相対パスは無視する
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "delvedown" / "scores.json"


def load_scores(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise ScoreFileError(f"{path} を読めません: {e}") from e
    if not isinstance(data, list) or not all(isinstance(d, dict) and isinstance(d.get("score"), int) for d in data):
        raise ScoreFileError(f"{path} の形が想定と違います")
    return data


def add_score(path: Path, entry: dict) -> tuple[int | None, list[dict]]:
    """entry を足して保存する。(順位 1〜10 か None, 保存後の一覧) を返す。"""
    scores = load_scores(path) + [entry]
    scores.sort(key=lambda d: -d["score"])  # 安定ソートなので同点は先に出した方が上
    scores = scores[:KEEP]
    rank = next((i + 1 for i, d in enumerate(scores) if d is entry), None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return rank, scores
