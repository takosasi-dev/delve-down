import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delvedown import dungeon  # noqa: E402
from delvedown.dungeon import FLOOR, MAP_H, MAP_W, STAIRS, WALL  # noqa: E402
from delvedown.fov import compute_fov  # noqa: E402
from delvedown.game import (  # noqa: E402
    BOSS, INV_LIMIT, KINDS, MAX_DEPTH, Game, Item, Monster, Player, autoplay, bot_action, damage,
)


def flood(tiles, start):
    seen, todo = {start}, [start]
    while todo:
        x, y = todo.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if n not in seen and 0 <= n[0] < MAP_W and 0 <= n[1] < MAP_H and tiles[n[1]][n[0]] != WALL:
                    seen.add(n)
                    todo.append(n)
    return seen


def open_game(seed=1):
    """壁で囲った 1 部屋だけの階に差し替えたゲーム(敵も物も無し)。"""
    g = Game(seed)
    g.tiles = [[WALL] * MAP_W for _ in range(MAP_H)]
    for y in range(1, MAP_H - 1):
        for x in range(1, MAP_W - 1):
            g.tiles[y][x] = FLOOR
    g.monsters, g.items, g.stairs = [], {}, None
    g.player.x, g.player.y = 10, 10
    g.update_fov()
    return g


class TestDungeon(unittest.TestCase):
    def test_many_seeds_connected(self):
        for seed in range(300):
            f = dungeon.generate(random.Random(seed), with_stairs=seed % 5 != 0)
            floors = {(x, y) for y in range(MAP_H) for x in range(MAP_W) if f.tiles[y][x] != WALL}
            reach = flood(f.tiles, f.start)
            self.assertEqual(reach, floors, f"seed {seed}: つながっていない床がある")
            for r in f.rooms:
                self.assertTrue(set(r.cells()) <= reach)
            if f.stairs:
                self.assertIn(f.stairs, reach)
                self.assertEqual(f.tiles[f.stairs[1]][f.stairs[0]], STAIRS)
            else:
                self.assertFalse(any(STAIRS in row for row in f.tiles))
            # 外周は全部壁
            self.assertTrue(all(c == WALL for c in f.tiles[0] + f.tiles[-1]))
            self.assertTrue(all(row[0] == WALL and row[-1] == WALL for row in f.tiles))

    def test_same_seed_same_map(self):
        a = dungeon.generate(random.Random(42))
        b = dungeon.generate(random.Random(42))
        self.assertEqual(a.tiles, b.tiles)
        self.assertEqual(a.start, b.start)


class TestFov(unittest.TestCase):
    def setUp(self):
        self.w, self.h = 21, 21
        self.walls = {(10, 7)}  # (10,10) から真上 3 マスの柱

    def fov(self, radius=8):
        return compute_fov(10, 10, radius, lambda x, y: (x, y) in self.walls, self.w, self.h)

    def test_open_area_within_radius(self):
        self.walls = set()
        v = self.fov(5)
        self.assertIn((10, 10), v)
        self.assertIn((15, 10), v)
        self.assertIn((13, 13), v)
        self.assertNotIn((16, 10), v)

    def test_wall_blocks(self):
        v = self.fov()
        self.assertIn((10, 7), v)  # 壁そのものは見える
        self.assertNotIn((10, 6), v)
        self.assertNotIn((10, 4), v)
        self.assertIn((10, 13), v)

    def test_corridor(self):
        # 横 1 マスの通路の中からは通路の先まで見え、壁の向こうは見えない
        self.walls = {(x, y) for x in range(self.w) for y in range(self.h) if y != 10}
        v = self.fov()
        self.assertTrue(all((x, 10) in v for x in range(3, 18)))
        self.assertIn((10, 9), v)
        self.assertNotIn((10, 8), v)


class TestCombat(unittest.TestCase):
    def test_damage_range(self):
        rng = random.Random(0)
        vals = {damage(10, 4, rng) for _ in range(500)}
        self.assertEqual(vals, {5, 6, 7})
        self.assertEqual({damage(2, 9, rng) for _ in range(100)}, {1})

    def test_kill_gives_xp_and_count(self):
        g = open_game()
        m = Monster(KINDS[0], 11, 10, 1)
        g.monsters.append(m)
        g.act(("move", 1, 0))
        self.assertNotIn(m, g.monsters)
        self.assertEqual(g.kills, 1)
        self.assertEqual(g.player.xp, KINDS[0].xp)

    def test_monster_attacks_and_player_dies(self):
        g = open_game()
        troll = next(k for k in KINDS if k.trait == "regen")
        g.monsters.append(Monster(troll, 11, 11, 999))
        g.player.hp = 1
        g.act(("wait",))
        self.assertEqual(g.state, "dead")
        self.assertEqual(g.cause, troll.name)
        self.assertFalse(g.act(("wait",)))  # 死んだら何もできない

    def test_chase_when_visible(self):
        g = open_game()
        m = Monster(KINDS[2], 16, 10, 99)  # ゴブリン(個性なし)
        g.monsters.append(m)
        g.act(("wait",))
        self.assertEqual(max(abs(m.x - 10), abs(m.y - 10)), 5)

    def test_slow_moves_every_other_turn(self):
        g = open_game()
        ogre = next(k for k in KINDS if k.trait == "slow")
        m = Monster(ogre, 18, 10, 99)
        g.monsters.append(m)
        xs = []
        for _ in range(4):
            g.act(("wait",))
            xs.append(m.x)
        self.assertEqual(len(set(xs)), 3)  # 4 手で 2 歩

    def test_regen(self):
        g = open_game()
        troll = next(k for k in KINDS if k.trait == "regen")
        m = Monster(troll, 50, 3, troll.hp - 5)
        g.monsters.append(m)
        g.act(("wait",))
        self.assertEqual(m.hp, troll.hp - 4)


class TestLevelAndItems(unittest.TestCase):
    def test_level_up(self):
        p = Player()
        atk, hp = p.atk, p.max_hp
        self.assertEqual(p.gain_xp(p.xp_next - 1), 0)
        self.assertEqual(p.gain_xp(1), 1)
        self.assertEqual(p.level, 2)
        self.assertGreater(p.atk, atk)
        self.assertGreater(p.max_hp, hp)
        self.assertEqual(p.xp, 0)
        self.assertGreater(p.gain_xp(1000), 1)  # 一度に何段も上がる

    def test_potion(self):
        g = open_game()
        p = g.player
        p.hp = 1
        n = len(p.inventory)
        g.act(("use", 0))
        self.assertGreater(p.hp, 1)
        self.assertEqual(len(p.inventory), n - 1)

    def test_equip_and_swap(self):
        g = open_game()
        p = g.player
        sword, axe = Item("weapon", "剣", 3), Item("weapon", "斧", 5)
        p.inventory += [sword, axe]
        base = p.atk
        g.act(("use", len(p.inventory) - 2))
        self.assertEqual(p.atk, base + 3)
        g.act(("use", len(p.inventory) - 1))
        self.assertEqual(p.atk, base + 5)
        self.assertIn(sword, p.inventory)
        g.act(("use", len(p.inventory) - 1))  # もう一度で外す
        self.assertEqual(p.atk, base)
        mail = Item("armor", "鱗の鎧", 4)
        p.inventory.append(mail)
        d = p.df
        g.act(("use", len(p.inventory) - 1))
        self.assertEqual(p.df, d + 4)
        g.act(("drop", len(p.inventory) - 1))  # 置くと外れる
        self.assertEqual(p.df, d)
        self.assertIs(g.items[(p.x, p.y)], mail)

    def test_teleport_and_mapping(self):
        g = Game(5)
        p = g.player
        p.inventory = [Item("teleport", "テレポートの巻物"), Item("mapping", "地図の巻物")]
        g.monsters = []
        g.act(("use", 0))
        self.assertTrue(g.walkable(p.x, p.y))
        self.assertIn((p.x, p.y), g.visible)
        g.act(("use", 0))
        floors = {(x, y) for y in range(MAP_H) for x in range(MAP_W) if g.walkable(x, y)}
        self.assertTrue(floors <= g.seen)
        self.assertEqual(p.inventory, [])

    def test_pickup_gold_and_limit(self):
        g = open_game()
        p = g.player
        g.items[(11, 10)] = Item("gold", "金", 30)
        g.act(("move", 1, 0))
        self.assertEqual(p.gold, 30)
        p.inventory = [Item("potion", "回復薬") for _ in range(INV_LIMIT)]
        g.items[(12, 10)] = Item("mapping", "地図の巻物")
        g.act(("move", 1, 0))
        self.assertEqual(len(p.inventory), INV_LIMIT)
        self.assertIn((12, 10), g.items)  # 拾えずに残る

    def test_bad_index_does_nothing(self):
        g = open_game()
        t = g.turn
        self.assertFalse(g.act(("use", 99)))
        self.assertFalse(g.act(("drop", -1)))
        self.assertFalse(g.act(("move", 0, -20)))  # 壁
        self.assertEqual(g.turn, t)

    def test_descend_and_win(self):
        g = Game(3)
        p = g.player
        self.assertFalse(g.act(("descend",)))
        while g.depth < MAX_DEPTH:
            p.x, p.y = g.stairs
            g.act(("descend",))
        self.assertIsNone(g.stairs)
        boss = next(m for m in g.monsters if m.kind is BOSS)
        g.monsters = [boss]
        boss.hp = 1
        p.x, p.y = boss.x - 1, boss.y
        if not g.walkable(p.x, p.y):
            p.x, p.y = boss.x + 1, boss.y
        g.update_fov()
        g.act(("move", boss.x - p.x, 0))
        self.assertEqual(g.items[(boss.x, boss.y)].kind, "treasure")
        g.act(("move", boss.x - p.x, 0))
        self.assertEqual(g.state, "won")
        self.assertGreater(g.score, 2000)


class TestReplay(unittest.TestCase):
    def play(self, seed, bot_seed, steps=800):
        g = Game(seed)
        rng = random.Random(bot_seed)
        actions = []
        for _ in range(steps):
            if g.state != "playing":
                break
            a = bot_action(g, rng)
            actions.append(a)
            g.act(a)
        return g, actions

    def test_same_seed_same_inputs(self):
        a, actions = self.play(7, 1)
        b = Game(7)
        for act in actions:
            b.act(act)
        self.assertEqual(a.summary(), b.summary())
        self.assertEqual(a.messages, b.messages)
        self.assertEqual(a.tiles, b.tiles)

    def test_different_seed_differs(self):
        self.assertNotEqual(Game(1).tiles, Game(2).tiles)


class TestFuzz(unittest.TestCase):
    def test_random_inputs_until_death(self):
        deaths = 0
        steps = 0
        for seed in range(12):
            g = autoplay(seed, 3000, bot_seed=seed + 100)
            steps += g.turn
            deaths += g.state == "dead"
            self.assertIn(g.state, ("playing", "dead", "won"))
            p = g.player
            self.assertLessEqual(len(p.inventory), INV_LIMIT)
            self.assertLessEqual(p.hp, p.max_hp)
            self.assertTrue(g.walkable(p.x, p.y))
        self.assertGreaterEqual(deaths, 3)
        self.assertGreater(steps, 3000)

    def test_pure_random_actions(self):
        rng = random.Random(9)
        acts = [("wait",), ("descend",)]
        for seed in range(3):
            g = Game(seed)
            for _ in range(1500):
                r = rng.random()
                if r < 0.8:
                    a = ("move", rng.randint(-1, 1), rng.randint(-1, 1))
                elif r < 0.9:
                    a = (rng.choice(["use", "drop"]), rng.randrange(-1, INV_LIMIT + 1))
                else:
                    a = rng.choice(acts)
                g.act(a)


if __name__ == "__main__":
    unittest.main()
