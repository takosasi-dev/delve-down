"""階の自動生成。部屋を置き、x 順に隣どうしを L 字の通路でつなぐ。

順につなぐので全部の部屋が1本につながる(階段にも必ず行ける)。
curses は使わない。乱数は呼び出し側の random.Random だけを使う。
"""

from __future__ import annotations

from dataclasses import dataclass

MAP_W, MAP_H = 60, 20
WALL, FLOOR, STAIRS = "#", ".", ">"


@dataclass
class Room:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def overlaps(self, o: Room, gap: int = 1) -> bool:
        return (self.x - gap < o.x + o.w and o.x - gap < self.x + self.w
                and self.y - gap < o.y + o.h and o.y - gap < self.y + self.h)

    def cells(self) -> list[tuple[int, int]]:
        return [(x, y) for y in range(self.y, self.y + self.h)
                for x in range(self.x, self.x + self.w)]


@dataclass
class Floor:
    tiles: list[list[str]]
    rooms: list[Room]
    start: tuple[int, int]
    start_room: Room
    far_room: Room
    stairs: tuple[int, int] | None


def _line(tiles, a, b):
    (x1, y1), (x2, y2) = a, b
    for y in range(min(y1, y2), max(y1, y2) + 1):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            tiles[y][x] = FLOOR


def _connect(tiles, rng, a: Room, b: Room):
    (x1, y1), (x2, y2) = a.center, b.center
    corner = (x2, y1) if rng.random() < 0.5 else (x1, y2)
    _line(tiles, (x1, y1), corner)
    _line(tiles, corner, (x2, y2))


def generate(rng, with_stairs: bool = True, w: int = MAP_W, h: int = MAP_H) -> Floor:
    rooms: list[Room] = []
    while len(rooms) < 4:
        rooms = []
        for _ in range(80):
            rw, rh = rng.randint(4, 12), rng.randint(3, 6)
            r = Room(rng.randint(1, w - rw - 1), rng.randint(1, h - rh - 1), rw, rh)
            if not any(r.overlaps(o) for o in rooms):
                rooms.append(r)
            if len(rooms) >= 9:
                break

    tiles = [[WALL] * w for _ in range(h)]
    for r in rooms:
        for x, y in r.cells():
            tiles[y][x] = FLOOR
    rooms.sort(key=lambda r: r.center)
    for a, b in zip(rooms, rooms[1:]):
        _connect(tiles, rng, a, b)
    for _ in range(rng.randint(1, 2)):  # 行き止まりだらけにしないための輪
        a, b = rng.sample(rooms, 2)
        _connect(tiles, rng, a, b)

    start_room = rng.choice(rooms)
    start = rng.choice(start_room.cells())
    sx, sy = start_room.center
    far_room = max((r for r in rooms if r is not start_room),
                   key=lambda r: abs(r.center[0] - sx) + abs(r.center[1] - sy))
    stairs = None
    if with_stairs:
        stairs = rng.choice(far_room.cells())
        tiles[stairs[1]][stairs[0]] = STAIRS
    return Floor(tiles, rooms, start, start_room, far_room, stairs)
