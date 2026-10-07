"""画面に出す文字の組み立て(curses を使わない)。ui.py はこれを貼るだけ。"""

from __future__ import annotations

import unicodedata

from .game import INV_LIMIT, ITEM_GLYPHS, MAX_DEPTH, Game

PANEL_W = 19  # 右のステータス欄の幅
MSG_LINES = 4  # 下のメッセージ欄の行数


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def clip(s: str, n: int) -> str:
    out, w = [], 0
    for c in s:
        cw = width(c)
        if w + cw > n:
            break
        out.append(c)
        w += cw
    return "".join(out)


def pad(s: str, n: int) -> str:
    s = clip(s, n)
    return s + " " * (n - width(s))


def rpad(s: str, n: int) -> str:
    s = clip(s, n)
    return " " * (n - width(s)) + s


def cell(game: Game, x: int, y: int):
    """(文字, 色名, 記憶だけか) か、まだ見ていなければ None。"""
    pos = (x, y)
    if pos in game.visible:
        p = game.player
        if pos == (p.x, p.y):
            return ("@", "player", False)
        m = game.monster_at(x, y)
        if m:
            return (m.kind.glyph, m.kind.color, False)
        it = game.items.get(pos)
        if it:
            g, color = ITEM_GLYPHS[it.kind]
            return (g, color, False)
        t = game.tiles[y][x]
        return (t, "stairs" if t == ">" else "white", False)
    if pos in game.seen:
        return (game.tiles[y][x], "dim", True)
    return None


def status_lines(game: Game) -> list[tuple[str, str]]:
    p = game.player
    bar_w = PANEL_W - 2
    filled = (bar_w * p.hp + p.max_hp - 1) // p.max_hp if p.max_hp else 0
    hp_color = "red" if p.hp * 10 < p.max_hp * 3 else "green"
    return [
        ("DelveDown", "yellow"),
        (f"地下 {game.depth}/{MAX_DEPTH} 階", "white"),
        ("", "white"),
        (f"HP  {p.hp}/{p.max_hp}", hp_color),
        ("[" + "=" * filled + " " * (bar_w - filled) + "]", hp_color),
        (f"Lv {p.level}  経験 {p.xp}/{p.xp_next}", "white"),
        (f"攻撃 {p.atk}  防御 {p.df}", "white"),
        (f"所持金 {p.gold}", "yellow"),
        ("", "white"),
        ("武器 " + (f"{p.weapon.name}+{p.weapon.power}" if p.weapon else "なし"), "cyan"),
        ("防具 " + (f"{p.armor.name}+{p.armor.power}" if p.armor else "なし"), "cyan"),
        (f"持ち物 {len(p.inventory)}/{INV_LIMIT}", "white"),
        ("", "white"),
        (f"倒した数 {game.kills}", "white"),
        (f"ターン {game.turn}", "white"),
        ("", "white"),
        ("? 操作説明", "dim"),
    ]


def message_lines(game: Game, n: int = MSG_LINES) -> list[str]:
    return game.messages[-n:]


def inventory_lines(game: Game, drop: bool) -> list[str]:
    p = game.player
    head = "置く物を選ぶ" if drop else "持ち物"
    lines = [f"{head} ({len(p.inventory)}/{INV_LIMIT})", ""]
    for i, it in enumerate(p.inventory):
        mark = " (装備中)" if it is p.weapon or it is p.armor else ""
        lines.append(f" {chr(ord('a') + i)}) {it.label}{mark}")
    if not p.inventory:
        lines.append(" (何も持っていない)")
    lines += ["", "文字キー: 置く" if drop else "文字キー: 使う/装備/外す", "Esc: 閉じる"]
    return lines


HELP_LINES = [
    "操作説明",
    "",
    " 移動    矢印キー / hjkl / テンキー",
    " 斜め    y u b n / テンキー 7 9 1 3",
    " 攻撃    敵に向かって移動する",
    " 待つ    .  (テンキー 5)",
    " 降りる  >  (階段 > の上で)",
    " 持ち物  i  (文字キーで使う/装備)",
    " 置く    d  (文字キーで選ぶ)",
    " 終了    Q  (確認あり)",
    "",
    " 足元の物は自動で拾う。持てるのは10個まで。",
    " 10階のボスを倒して宝 * を取ればクリア。",
    "",
    " r ネズミ  b コウモリ  g ゴブリン  s スケルトン",
    " o オーク  O オーガ  T トロル  D 闇の竜",
    " ! 回復薬  ? 巻物  ) 武器  [ 防具  $ お金",
    "",
    "何かキーを押すと戻る",
]


def score_table(scores: list[dict], mark_rank: int | None = None) -> list[str]:
    if not scores:
        return ["(まだ記録がない)"]
    lines = [" 順位  スコア  結果    階  倒  所持金  Lv  日付"]
    for i, d in enumerate(scores, 1):
        res = "クリア" if d.get("won") else "死亡"
        mark = ">" if i == mark_rank else " "
        lines.append(
            f"{mark}{rpad(str(i), 3)}  {rpad(str(d['score']), 6)}  {pad(res, 6)} "
            f"{rpad(str(d.get('depth', '?')), 3)} {rpad(str(d.get('kills', '?')), 3)} "
            f"{rpad(str(d.get('gold', '?')), 7)} {rpad(str(d.get('level', '?')), 3)}  {d.get('date', '?')}")
    return lines


def result_lines(game: Game, rank: int | None, scores: list[dict] | None, note: str = "") -> list[str]:
    p = game.player
    head = "宝を手に入れた! クリア!" if game.state == "won" else f"{game.cause}に倒された……"
    lines = [
        head, "",
        f" 到達階    地下 {game.depth} 階",
        f" 倒した数  {game.kills}",
        f" 所持金    {p.gold}",
        f" レベル    {p.level}",
        f" ターン    {game.turn}",
        f" スコア    {game.score}",
        f" シード    {game.seed}  (--seed {game.seed} で同じダンジョン)",
        "",
    ]
    if note:
        lines += [note, ""]
    if scores is not None:
        lines.append("ハイスコア" + (f"  (今回は {rank} 位)" if rank else "  (今回は圏外)"))
        lines += score_table(scores, rank)
    lines.append("何かキーを押すと終わる")
    return lines
