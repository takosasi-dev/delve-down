import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delvedown import view  # noqa: E402
from delvedown.__main__ import main  # noqa: E402
from delvedown.dungeon import MAP_H, MAP_W  # noqa: E402
from delvedown.game import Game, Item  # noqa: E402
from delvedown.scores import ScoreFileError, add_score, default_path, load_scores  # noqa: E402


def entry(score, **kw):
    return {"score": score, "depth": 1, "kills": 0, "gold": 0, "level": 1, "won": False,
            "date": "2026-10-08", **kw}


class TestScores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "delvedown" / "scores.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_path(self):
        self.assertEqual(default_path({"XDG_DATA_HOME": "/x/data"}),
                         Path("/x/data") / "delvedown" / "scores.json")
        home = default_path({})
        self.assertEqual(home.parts[-4:], (".local", "share", "delvedown", "scores.json"))
        self.assertEqual(default_path({"XDG_DATA_HOME": "rel"}), home)  # 相対は無視

    def test_save_and_load_top10(self):
        self.assertEqual(load_scores(self.path), [])
        for s in [50, 10, 90, 30, 70, 20, 80, 40, 60, 100, 5, 55]:
            rank, scores = add_score(self.path, entry(s))
        self.assertEqual(rank, 6)  # 55 は 6 位
        loaded = load_scores(self.path)
        self.assertEqual([d["score"] for d in loaded], [100, 90, 80, 70, 60, 55, 50, 40, 30, 20])
        rank, _ = add_score(self.path, entry(1))
        self.assertIsNone(rank)
        rank, _ = add_score(self.path, entry(100, gold=7))
        self.assertEqual(rank, 2)  # 同点は先の記録が上
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_broken_file_is_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{oops", encoding="utf-8")
        with self.assertRaises(ScoreFileError):
            add_score(self.path, entry(1))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{oops")
        self.path.write_text('[{"score": "x"}]', encoding="utf-8")
        with self.assertRaises(ScoreFileError):
            load_scores(self.path)

    def test_cli_scores_json(self):
        add_score(self.path, entry(42))
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["--scores", "--json", "--scores-file", str(self.path)]), 0)
        self.assertEqual(json.loads(buf.getvalue())[0]["score"], 42)

    def test_cli_autoplay(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["--seed", "3", "--autoplay", "50"]), 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["seed"], 3)
        self.assertIn(out["state"], ("playing", "dead", "won"))


class TestView(unittest.TestCase):
    def test_width_and_clip(self):
        self.assertEqual(view.width("abc"), 3)
        self.assertEqual(view.width("地下3階"), 7)
        self.assertEqual(view.clip("地下3階", 4), "地下")
        self.assertEqual(view.clip("地下3階", 3), "地")
        self.assertEqual(view.width(view.pad("地下", 7)), 7)
        self.assertEqual(view.rpad("12", 4), "  12")

    def test_panel_fits(self):
        g = Game(1)
        p = g.player
        p.level, p.xp, p.hp, p.max_hp, p.gold = 99, 999, 999, 999, 99999
        p.weapon, p.armor = Item("weapon", "大剣", 7), Item("armor", "鎖かたびら", 2)
        for text, _ in view.status_lines(g):
            self.assertLessEqual(view.width(text), view.PANEL_W, text)
        self.assertLessEqual(len(view.status_lines(g)), MAP_H)

    def test_boxes_fit_map(self):
        g = Game(1)
        g.player.inventory = [Item("armor", "鎖かたびら", 2)] * 10
        for lines in (view.HELP_LINES, view.inventory_lines(g, False), view.inventory_lines(g, True)):
            self.assertLessEqual(max(view.width(s) for s in lines) + 4, MAP_W)
            self.assertLessEqual(1 + len(lines) + 2, 24)  # 枠は 1 行目から、24 行に収まる

    def test_result_fits_80x24(self):
        g = Game(1)
        g.state, g.cause = "dead", "スケルトン"
        scores = [entry(10 ** 6, won=True, depth=10, kills=999, gold=999999, level=99)] * 10
        lines = view.result_lines(g, 3, scores)
        self.assertLessEqual(len(lines), 23)
        for s in lines:
            self.assertLessEqual(view.width(s) + 2, 80, s)
        self.assertIn("今回は 3 位", "\n".join(lines))
        self.assertIn("今回は圏外", "\n".join(view.result_lines(g, None, scores)))

    def test_cells(self):
        g = Game(1)
        p = g.player
        self.assertEqual(view.cell(g, p.x, p.y)[0], "@")
        unseen = next((x, y) for y in range(MAP_H) for x in range(MAP_W) if (x, y) not in g.seen)
        self.assertIsNone(view.cell(g, *unseen))
        g.seen.add(unseen)
        self.assertTrue(view.cell(g, *unseen)[2])  # 覚えているだけのマス


if __name__ == "__main__":
    unittest.main()
