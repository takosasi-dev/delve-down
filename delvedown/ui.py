"""curses の画面と入力。中身は game.py、文字の組み立ては view.py。"""

from __future__ import annotations

import curses
import datetime
import locale
import os

from . import view
from .dungeon import MAP_H, MAP_W
from .game import Game
from .scores import ScoreFileError, add_score

MIN_W, MIN_H = 80, 24
ESC = 27

_DIRS = {
    "h": (-1, 0), "j": (0, 1), "k": (0, -1), "l": (1, 0),
    "y": (-1, -1), "u": (1, -1), "b": (-1, 1), "n": (1, 1),
    "4": (-1, 0), "2": (0, 1), "8": (0, -1), "6": (1, 0),
    "7": (-1, -1), "9": (1, -1), "1": (-1, 1), "3": (1, 1),
}
MOVE_KEYS = {ord(k): d for k, d in _DIRS.items()}
MOVE_KEYS.update({
    curses.KEY_LEFT: (-1, 0), curses.KEY_DOWN: (0, 1), curses.KEY_UP: (0, -1), curses.KEY_RIGHT: (1, 0),
    curses.KEY_HOME: (-1, -1), curses.KEY_PPAGE: (1, -1), curses.KEY_END: (-1, 1), curses.KEY_NPAGE: (1, 1),
    curses.KEY_A1: (-1, -1), curses.KEY_A3: (1, -1), curses.KEY_C1: (-1, 1), curses.KEY_C3: (1, 1),
})
WAIT_KEYS = {ord("."), ord("5"), curses.KEY_B2}

_COLORS = {"white": curses.COLOR_WHITE, "red": curses.COLOR_RED, "green": curses.COLOR_GREEN,
           "yellow": curses.COLOR_YELLOW, "blue": curses.COLOR_BLUE, "magenta": curses.COLOR_MAGENTA,
           "cyan": curses.COLOR_CYAN}


def key_to_action(key: int):
    if key in MOVE_KEYS:
        return ("move", *MOVE_KEYS[key])
    if key in WAIT_KEYS:
        return ("wait",)
    if key == ord(">"):
        return ("descend",)
    return None


class App:
    def __init__(self, scr, game: Game, scores_path):
        self.scr = scr
        self.game = game
        self.scores_path = scores_path
        self.prompt = ""
        self.attrs: dict[str, int] = {}
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK
            for i, (name, c) in enumerate(_COLORS.items(), 1):
                curses.init_pair(i, c, bg)
                self.attrs[name] = curses.color_pair(i)
            self.attrs["dim"] = self.attrs["blue"]
            self.attrs["player"] = self.attrs["white"] | curses.A_BOLD
            self.attrs["stairs"] = self.attrs["yellow"] | curses.A_BOLD
        else:  # 色の無い端末: 文字だけで区別する
            self.attrs = {"dim": curses.A_DIM, "player": curses.A_BOLD, "stairs": curses.A_BOLD}

    # ---- 描画 ----
    def put(self, y: int, x: int, text: str, color: str = "white") -> None:
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            try:
                self.scr.addstr(y, x, view.clip(text, w - x), self.attrs.get(color, 0))
            except curses.error:  # 右下の隅に書くと出るが、書けてはいる
                pass

    def too_small(self) -> bool:
        h, w = self.scr.getmaxyx()
        if h >= MIN_H and w >= MIN_W:
            return False
        self.scr.erase()
        self.put(0, 0, "端末を広げてください")
        self.put(1, 0, f"{MIN_W}x{MIN_H} 以上が必要")
        self.put(2, 0, f"(いまは {w}x{h})")
        self.scr.refresh()
        return True

    def draw_game(self) -> None:
        g = self.game
        self.scr.erase()
        for y in range(MAP_H):  # 同じ色が続く所はまとめて書く
            x0, run, color = 0, "", None
            for x in range(MAP_W + 1):
                c = view.cell(g, x, y) if x < MAP_W else ("", "end", False)
                ch, col = (c[0], c[1]) if c else (" ", "white")
                if col != color:
                    if run.strip():
                        self.put(y, x0, run, color)
                    x0, run, color = x, "", col
                run += ch
        for i, (text, color) in enumerate(view.status_lines(g)):
            self.put(i, MAP_W + 1, view.clip(text, view.PANEL_W), color)
        msgs = view.message_lines(g)
        if self.prompt:
            msgs = (msgs + [self.prompt])[-view.MSG_LINES:]
        for i, m in enumerate(msgs):
            newest = i == len(msgs) - 1
            self.put(MAP_H + i, 0, m, "white" if newest else "dim")

    def draw_box(self, lines: list[str]) -> None:
        bw = max(view.width(s) for s in lines) + 4
        x0 = max(0, (MAP_W - bw) // 2)
        self.put(1, x0, "+" + "-" * (bw - 2) + "+")
        for i, s in enumerate(lines):
            self.put(2 + i, x0, "| " + view.pad(s, bw - 4) + " |")
        self.put(2 + len(lines), x0, "+" + "-" * (bw - 2) + "+")

    def frame(self, draw) -> int | None:
        """画面を描いてキーを1つ待つ。狭い・サイズが変わったときは None。"""
        if self.too_small():
            self.scr.getch()
            return None
        draw()
        self.scr.refresh()
        key = self.scr.getch()
        return None if key == curses.KEY_RESIZE else key

    # ---- 流れ ----
    def run(self) -> None:
        g = self.game
        while g.state == "playing":
            key = self.frame(self.draw_game)
            if key is None:
                continue
            if key == ord("Q"):
                if self.confirm_quit():
                    return
            elif key == ord("?"):
                self.wait_any(lambda: (self.draw_game(), self.draw_box(view.HELP_LINES)))
            elif key in (ord("i"), ord("d")):
                self.inventory(drop=key == ord("d"))
            else:
                action = key_to_action(key)
                if action:
                    g.act(action)
        self.prompt = "(何かキーを押すと結果へ)"
        self.wait_any(self.draw_game)
        self.result()

    def wait_any(self, draw) -> int:
        while True:
            key = self.frame(draw)
            if key is not None:
                return key

    def confirm_quit(self) -> bool:
        self.prompt = "本当に終了しますか? (y/n)"
        key = self.wait_any(self.draw_game)
        self.prompt = ""
        return key in (ord("y"), ord("Y"))

    def inventory(self, drop: bool) -> None:
        lines = view.inventory_lines(self.game, drop)
        key = self.wait_any(lambda: (self.draw_game(), self.draw_box(lines)))
        i = key - ord("a")
        if 0 <= i < len(self.game.player.inventory):
            self.game.act(("drop", i) if drop else ("use", i))

    def result(self) -> None:
        g = self.game
        entry = {**{k: v for k, v in g.summary().items() if k != "state"},
                 "won": g.state == "won", "date": datetime.date.today().isoformat()}
        rank, scores, note = None, None, ""
        try:
            rank, scores = add_score(self.scores_path, entry)
        except (ScoreFileError, OSError) as e:
            note = f"スコアを保存できませんでした: {e}"
        lines = view.result_lines(g, rank, scores, note)

        def draw():
            self.scr.erase()
            for i, s in enumerate(lines):
                self.put(i, 2, s, "yellow" if i == 0 else "white")
        self.wait_any(draw)


def run(seed: int, scores_path) -> None:
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(lambda scr: App(scr, Game(seed), scores_path).run())
