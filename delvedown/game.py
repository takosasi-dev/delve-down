"""ゲームの中身(curses を使わない)。

乱数は Game.rng(random.Random(seed))1本だけ。同じシードと同じ行動の列なら同じ結果になる。
行動は ("move", dx, dy) / ("wait",) / ("descend",) / ("use", i) / ("drop", i) のタプル。
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

from .dungeon import MAP_H, MAP_W, STAIRS, WALL, generate
from .fov import compute_fov

MAX_DEPTH = 10
FOV_RADIUS = 8
INV_LIMIT = 10
MSG_KEEP = 100
REGEN_EVERY = 4  # プレイヤーは何ターンごとに HP が 1 戻るか

DIRS8 = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))


@dataclass(frozen=True)
class MonsterKind:
    name: str
    glyph: str
    color: str
    hp: int
    atk: int
    df: int
    xp: int
    depths: tuple[int, int]
    trait: str = ""  # erratic=ふらふら動く / slow=2手に1回 / regen=毎ターン回復 / boss=見えるまで動かない


KINDS = (
    MonsterKind("ネズミ", "r", "yellow", 4, 3, 0, 2, (1, 3)),
    MonsterKind("コウモリ", "b", "magenta", 5, 3, 0, 3, (1, 5), "erratic"),
    MonsterKind("ゴブリン", "g", "green", 10, 5, 1, 6, (2, 6)),
    MonsterKind("スケルトン", "s", "white", 16, 8, 3, 12, (4, 8)),
    MonsterKind("オーク", "o", "red", 24, 10, 4, 18, (5, 10)),
    MonsterKind("オーガ", "O", "yellow", 45, 16, 5, 35, (7, 10), "slow"),
    MonsterKind("トロル", "T", "green", 34, 13, 6, 30, (8, 10), "regen"),
)
BOSS = MonsterKind("闇の竜", "D", "red", 150, 24, 10, 0, (MAX_DEPTH, MAX_DEPTH), "boss")


@dataclass
class Monster:
    kind: MonsterKind
    x: int
    y: int
    hp: int

    @property
    def name(self) -> str:
        return self.kind.name


@dataclass
class Item:
    kind: str  # potion / teleport / mapping / weapon / armor / gold / treasure
    name: str
    power: int = 0

    @property
    def label(self) -> str:
        if self.kind == "weapon":
            return f"{self.name}(攻+{self.power})"
        if self.kind == "armor":
            return f"{self.name}(防+{self.power})"
        if self.kind == "gold":
            return f"{self.power} ゴールド"
        return self.name


ITEM_GLYPHS = {
    "potion": ("!", "red"), "teleport": ("?", "cyan"), "mapping": ("?", "yellow"),
    "weapon": (")", "cyan"), "armor": ("[", "cyan"), "gold": ("$", "yellow"),
    "treasure": ("*", "magenta"),
}
WEAPONS = ((1, "短剣", 1), (3, "剣", 3), (5, "斧", 5), (8, "大剣", 7))  # (出る階, 名前, 強さ)
ARMORS = ((1, "革の鎧", 1), (3, "鎖かたびら", 2), (5, "鱗の鎧", 4), (8, "板金鎧", 6))
ITEM_WEIGHTS = (("potion", 40), ("teleport", 12), ("mapping", 12), ("weapon", 10), ("armor", 10))


def potion() -> Item:
    return Item("potion", "回復薬")


@dataclass
class Player:
    x: int = 0
    y: int = 0
    hp: int = 30
    max_hp: int = 30
    base_atk: int = 5
    base_def: int = 1
    level: int = 1
    xp: int = 0
    gold: int = 0
    inventory: list[Item] = field(default_factory=list)
    weapon: Item | None = None
    armor: Item | None = None

    @property
    def atk(self) -> int:
        return self.base_atk + (self.weapon.power if self.weapon else 0)

    @property
    def df(self) -> int:
        return self.base_def + (self.armor.power if self.armor else 0)

    @property
    def xp_next(self) -> int:
        return 10 * self.level

    def gain_xp(self, n: int) -> int:
        """経験値を足し、上がったレベルの数を返す。"""
        self.xp += n
        ups = 0
        while self.xp >= self.xp_next:
            self.xp -= self.xp_next
            self.level += 1
            ups += 1
            self.max_hp += 6
            self.hp += 6
            self.base_atk += 1
            if self.level % 2 == 0:
                self.base_def += 1
        return ups


def damage(atk: int, df: int, rng: random.Random) -> int:
    """攻撃 - 防御 を ±1 揺らす。最低 1。"""
    return max(1, atk - df + rng.randint(-1, 1))


def score_of(depth: int, kills: int, gold: int, level: int, won: bool) -> int:
    return depth * 100 + kills * 10 + gold + (level - 1) * 50 + (2000 if won else 0)


class Game:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.player = Player(inventory=[potion(), potion()])
        self.depth = 0
        self.turn = 0
        self.kills = 0
        self.state = "playing"  # playing / dead / won
        self.cause = ""
        self.messages: list[str] = []
        self.say("DelveDown へようこそ。10階の宝を目指せ。(? で操作説明)")
        self.new_floor()

    # ---- 階 ----
    def new_floor(self) -> None:
        self.depth += 1
        floor = generate(self.rng, with_stairs=self.depth < MAX_DEPTH)
        self.tiles = floor.tiles
        self.rooms = floor.rooms
        self.stairs = floor.stairs
        self.player.x, self.player.y = floor.start
        self.seen: set[tuple[int, int]] = set()
        self.monsters: list[Monster] = []
        self.items: dict[tuple[int, int], Item] = {}
        others = [r for r in floor.rooms if r is not floor.start_room]
        if self.depth == MAX_DEPTH:
            bx, by = floor.far_room.center
            self.monsters.append(Monster(BOSS, bx, by, BOSS.hp))
            self.say("地の底だ。強い気配がする……")
        else:
            self.say(f"地下 {self.depth} 階に着いた。")
        kinds = [k for k in KINDS if k.depths[0] <= self.depth <= k.depths[1]]
        for _ in range(3 + self.depth + self.rng.randint(0, 2)):
            pos = self._free_cell(others)
            if pos:
                k = self.rng.choice(kinds)
                self.monsters.append(Monster(k, pos[0], pos[1], k.hp))
        for _ in range(3 + self.rng.randint(0, 2)):
            pos = self._free_cell(floor.rooms)
            if pos:
                self.items[pos] = self._random_item()
        for _ in range(2 + self.rng.randint(0, 2)):
            pos = self._free_cell(floor.rooms)
            if pos:
                self.items[pos] = Item("gold", "金", self.rng.randint(5, 15) * self.depth)
        self.update_fov()

    def _free_cell(self, rooms):
        for _ in range(50):
            x, y = self.rng.choice(self.rng.choice(rooms).cells())
            if ((x, y) != (self.player.x, self.player.y) and (x, y) != self.stairs
                    and (x, y) not in self.items and not self.monster_at(x, y)):
                return (x, y)
        return None

    def _random_item(self) -> Item:
        kind = self.rng.choices([k for k, _ in ITEM_WEIGHTS], [w for _, w in ITEM_WEIGHTS])[0]
        if kind in ("weapon", "armor"):
            table = WEAPONS if kind == "weapon" else ARMORS
            ok = [t for t in table if t[0] <= self.depth]
            _, name, power = self.rng.choice(ok[-2:])
            return Item(kind, name, power)
        return {"potion": potion(), "teleport": Item("teleport", "テレポートの巻物"),
                "mapping": Item("mapping", "地図の巻物")}[kind]

    # ---- 問い合わせ ----
    def tile(self, x: int, y: int) -> str:
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            return self.tiles[y][x]
        return WALL

    def walkable(self, x: int, y: int) -> bool:
        return self.tile(x, y) != WALL

    def monster_at(self, x: int, y: int) -> Monster | None:
        for m in self.monsters:
            if m.x == x and m.y == y:
                return m
        return None

    def update_fov(self) -> None:
        p = self.player
        self.visible = compute_fov(p.x, p.y, FOV_RADIUS,
                                   lambda x, y: self.tiles[y][x] == WALL, MAP_W, MAP_H)
        self.seen |= self.visible

    def distance_map(self, target: tuple[int, int]) -> dict[tuple[int, int], int]:
        dist = {target: 0}
        q = deque([target])
        while q:
            x, y = q.popleft()
            for dx, dy in DIRS8:
                n = (x + dx, y + dy)
                if n not in dist and self.walkable(*n):
                    dist[n] = dist[(x, y)] + 1
                    q.append(n)
        return dist

    def say(self, msg: str) -> None:
        self.messages.append(msg)
        del self.messages[:-MSG_KEEP]

    @property
    def score(self) -> int:
        p = self.player
        return score_of(self.depth, self.kills, p.gold, p.level, self.state == "won")

    def summary(self) -> dict:
        p = self.player
        return {"seed": self.seed, "state": self.state, "cause": self.cause,
                "depth": self.depth, "kills": self.kills, "gold": p.gold,
                "level": p.level, "turns": self.turn, "score": self.score}

    # ---- 行動 ----
    def act(self, action: tuple) -> bool:
        """1手進める。ターンを使ったら True。"""
        if self.state != "playing":
            return False
        kind = action[0]
        if kind == "move":
            took = self._move(action[1], action[2])
        elif kind == "wait":
            took = True
        elif kind == "descend":
            took = self._descend()
        elif kind == "use":
            took = self._use(action[1])
        elif kind == "drop":
            took = self._drop(action[1])
        else:
            raise ValueError(f"知らない行動: {action!r}")
        if took and self.state == "playing":
            self._end_turn()
        return took

    def _move(self, dx: int, dy: int) -> bool:
        p = self.player
        nx, ny = p.x + dx, p.y + dy
        m = self.monster_at(nx, ny)
        if m:
            self._player_attacks(m)
            return True
        if not self.walkable(nx, ny):
            return False
        p.x, p.y = nx, ny
        self._pick_up()
        if (p.x, p.y) == self.stairs:
            self.say("下り階段がある。(> で降りる)")
        return True

    def _pick_up(self) -> None:
        p = self.player
        pos = (p.x, p.y)
        it = self.items.get(pos)
        if not it:
            return
        if it.kind == "gold":
            p.gold += it.power
            self.say(f"{it.power} ゴールドを拾った。")
        elif it.kind == "treasure":
            self.say("宝を手に入れた! ダンジョンを制覇した!")
            self.state = "won"
        elif len(p.inventory) >= INV_LIMIT:
            self.say(f"{it.label}がある。持ち物がいっぱいで拾えない。")
            return
        else:
            p.inventory.append(it)
            self.say(f"{it.label}を拾った。")
        del self.items[pos]

    def _descend(self) -> bool:
        p = self.player
        if (p.x, p.y) != self.stairs:
            self.say("ここに下り階段はない。")
            return False
        self.turn += 1
        self.new_floor()
        return False  # 新しい階の敵はまだ動かさない

    def _use(self, i: int) -> bool:
        p = self.player
        if not 0 <= i < len(p.inventory):
            return False
        it = p.inventory[i]
        if it.kind == "potion":
            heal = max(15, p.max_hp // 2)
            p.hp = min(p.max_hp, p.hp + heal)
            self.say("回復薬を飲んだ。体が楽になった。")
        elif it.kind == "teleport":
            cells = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
                     if self.walkable(x, y) and not self.monster_at(x, y)]
            p.x, p.y = self.rng.choice(cells)
            self.say("テレポートの巻物を読んだ。景色が変わった!")
            self.update_fov()
            self._pick_up()
        elif it.kind == "mapping":
            self.seen |= {(x, y) for y in range(MAP_H) for x in range(MAP_W)
                          if self.walkable(x, y) or any(self.walkable(x + dx, y + dy) for dx, dy in DIRS8)}
            self.say("地図の巻物を読んだ。この階の形が分かった。")
        elif it.kind in ("weapon", "armor"):
            slot = "weapon" if it.kind == "weapon" else "armor"
            if getattr(p, slot) is it:
                setattr(p, slot, None)
                self.say(f"{it.label}を外した。")
            else:
                setattr(p, slot, it)
                self.say(f"{it.label}を装備した。")
            return True
        p.inventory.pop(i)
        return True

    def _drop(self, i: int) -> bool:
        p = self.player
        if not 0 <= i < len(p.inventory):
            return False
        if (p.x, p.y) in self.items or (p.x, p.y) == self.stairs:
            self.say("ここには置けない。")
            return False
        it = p.inventory.pop(i)
        if p.weapon is it:
            p.weapon = None
        if p.armor is it:
            p.armor = None
        self.items[(p.x, p.y)] = it
        self.say(f"{it.label}を置いた。")
        return True

    # ---- 戦闘と敵 ----
    def _player_attacks(self, m: Monster) -> None:
        p = self.player
        d = damage(p.atk, m.kind.df, self.rng)
        m.hp -= d
        if m.hp > 0:
            self.say(f"{m.name}に {d} のダメージ。")
            return
        self.monsters.remove(m)
        self.kills += 1
        self.say(f"{m.name}を倒した。")
        if m.kind is BOSS:
            self.items[(m.x, m.y)] = Item("treasure", "宝")
            self.say("闇の竜が守っていた宝が落ちた!")
        if p.gain_xp(m.kind.xp):
            self.say(f"レベルが {p.level} に上がった!")

    def _monster_attacks(self, m: Monster) -> None:
        p = self.player
        d = damage(m.kind.atk, p.df, self.rng)
        p.hp -= d
        self.say(f"{m.name}の攻撃。{d} のダメージを受けた。")
        if p.hp <= 0:
            p.hp = 0
            self.state = "dead"
            self.cause = m.name
            self.say(f"{m.name}に倒された……")

    def _step(self, m: Monster, dx: int, dy: int) -> None:
        nx, ny = m.x + dx, m.y + dy
        p = self.player
        if self.walkable(nx, ny) and not self.monster_at(nx, ny) and (nx, ny) != (p.x, p.y):
            m.x, m.y = nx, ny

    def _end_turn(self) -> None:
        self.turn += 1
        p = self.player
        if self.turn % REGEN_EVERY == 0 and p.hp < p.max_hp:
            p.hp += 1
        self.update_fov()
        dist = self.distance_map((p.x, p.y))
        for m in list(self.monsters):
            if self.state != "playing":
                break
            t = m.kind.trait
            if t == "regen" and m.hp < m.kind.hp:
                m.hp += 1
            if t == "slow" and self.turn % 2:
                continue
            sees = (m.x, m.y) in self.visible
            if not sees:
                if t != "boss" and self.rng.random() < 0.5:
                    self._step(m, *self.rng.choice(DIRS8))
                continue
            if t == "erratic" and self.rng.random() < 0.5:
                self._step(m, *self.rng.choice(DIRS8))
                continue
            if max(abs(m.x - p.x), abs(m.y - p.y)) == 1:
                self._monster_attacks(m)
                continue
            here = dist.get((m.x, m.y), 10 ** 9)
            best = None
            for dx, dy in DIRS8:
                n = (m.x + dx, m.y + dy)
                if n in dist and dist[n] < here and not self.monster_at(*n):
                    if best is None or dist[n] < dist[best]:
                        best = n
            if best:
                m.x, m.y = best


# ---- 画面なしで遊ぶ(--autoplay とテスト用) ----
def bot_action(game: Game, rng: random.Random) -> tuple:
    """そこそこ賢いが、ときどき出鱈目なことをする操作役。"""
    p = game.player
    inv = p.inventory
    if p.hp * 10 < p.max_hp * 4:
        for i, it in enumerate(inv):
            if it.kind == "potion":
                return ("use", i)
    for i, it in enumerate(inv):
        cur = p.weapon if it.kind == "weapon" else p.armor if it.kind == "armor" else it
        if it is not cur and (cur is None or it.power > cur.power):
            return ("use", i)
    if len(inv) >= INV_LIMIT:
        for i, it in enumerate(inv):
            if it.kind in ("weapon", "armor") and it is not p.weapon and it is not p.armor:
                return ("drop", i)
    r = rng.random()
    if r < 0.03:
        return ("use", rng.randrange(INV_LIMIT + 2))
    if r < 0.04:
        return ("drop", rng.randrange(INV_LIMIT + 2))
    if r < 0.06:
        return (rng.choice([("wait",), ("descend",)]))
    if r < 0.25:
        return ("move", *rng.choice(DIRS8))
    if (p.x, p.y) == game.stairs:
        return ("descend",)
    # 見えている敵 → 見えている物 → 階段 の順に向かう(人が遊ぶのに近い動き)
    here = (p.x, p.y)
    seen_things = [(m.x, m.y) for m in game.monsters if (m.x, m.y) in game.visible]
    if not seen_things and p.hp * 10 < p.max_hp * 7:
        return ("wait",)  # 敵がいなければ休む
    for pos, it in game.items.items():
        cur = p.weapon if it.kind == "weapon" else p.armor if it.kind == "armor" else None
        wanted = it.kind in ("gold", "treasure") or (len(inv) < INV_LIMIT and (
            cur is None or it.power > cur.power))
        if pos in game.visible and pos != here and wanted:
            seen_things.append(pos)
    target = min(seen_things, key=lambda q: max(abs(q[0] - here[0]), abs(q[1] - here[1])),
                 default=game.stairs)
    if target is None:
        target = next((pos for pos, it in game.items.items() if it.kind == "treasure"), None)
        if target is None:
            boss = next((m for m in game.monsters if m.kind is BOSS), None)
            target = (boss.x, boss.y) if boss else None
    if target:
        dist = game.distance_map(target)
        here = dist.get((p.x, p.y), 10 ** 9)
        for dx, dy in DIRS8:
            n = (p.x + dx, p.y + dy)
            if dist.get(n, 10 ** 9) < here:
                return ("move", dx, dy)
    return ("wait",)


def autoplay(seed: int, steps: int, bot_seed: int = 0) -> Game:
    game = Game(seed)
    rng = random.Random(bot_seed)
    for _ in range(steps):
        if game.state != "playing":
            break
        game.act(bot_action(game, rng))
    return game
