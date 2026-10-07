"""コマンド入口。引数なしで curses の画面を開く。"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from . import __version__, view
from .game import autoplay
from .scores import ScoreFileError, default_path, load_scores


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="delvedown", description="文字で描くダンジョンのローグライク")
    ap.add_argument("--seed", type=int, help="ダンジョンのシード(同じ値で同じダンジョン)")
    ap.add_argument("--scores", action="store_true", help="ハイスコアを表示して終わる")
    ap.add_argument("--autoplay", type=int, metavar="STEPS",
                    help="画面なしで自動操作役に STEPS 手遊ばせ、結果を JSON で出す(スコアは保存しない)")
    ap.add_argument("--json", action="store_true", help="--scores を JSON で出す")
    ap.add_argument("--scores-file", type=Path, help="スコアファイルの場所(既定は XDG_DATA_HOME 配下)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows の cp932 でも日本語で落ちないように

    path = args.scores_file or default_path()
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1_000_000)

    if args.scores:
        try:
            scores = load_scores(path)
        except ScoreFileError as e:
            print(e, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(scores, ensure_ascii=False, indent=1))
        else:
            print("\n".join(view.score_table(scores)))
        return 0

    if args.autoplay is not None:
        print(json.dumps(autoplay(seed, args.autoplay).summary(), ensure_ascii=False))
        return 0

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("端末で起動してください(画面なしなら --scores か --autoplay)", file=sys.stderr)
        return 2
    try:
        from . import ui
    except ImportError:
        print("curses が使えません(Windows では WSL などで遊んでください)", file=sys.stderr)
        return 2
    ui.run(seed, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
