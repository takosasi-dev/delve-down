"""本物の curses を疑似端末(pty)で動かす。Linux だけ。"""

import os
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    import curses  # noqa: F401
    import fcntl
    import pty
    import signal
    import struct
    import termios
    OK = sys.platform.startswith("linux")
except ImportError:
    OK = False


@unittest.skipUnless(OK, "Linux の curses と pty が要る")
class TestTty(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = b""
        self.pid, self.fd = 0, None

    def tearDown(self):
        if self.pid > 0:  # -1 を kill に渡すと全プロセスに届くので必ず確かめる
            try:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        if self.fd is not None:
            os.close(self.fd)
        self.tmp.cleanup()

    def spawn(self, cols, rows, seed=1):
        pid, fd = pty.fork()
        if pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            env = {**os.environ, "TERM": "xterm-256color", "XDG_DATA_HOME": self.tmp.name,
                   "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
            os.execvpe(sys.executable, [sys.executable, "-m", "delvedown", "--seed", str(seed)], env)
        self.pid, self.fd = pid, fd

    def resize(self, cols, rows):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.kill(self.pid, signal.SIGWINCH)

    def read_for(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            import select
            r, _, _ = select.select([self.fd], [], [], max(0, min(0.05, end - time.time())))
            if r:
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                self.out += chunk

    def wait_text(self, text, seconds=5):
        end = time.time() + seconds
        while time.time() < end:
            if text.encode() in self.out:
                return
            self.read_for(0.1)
        self.fail(f"{text!r} が出ない: {self.out[-500:]!r}")

    def send(self, keys, gap=0.0):
        for k in keys:
            os.write(self.fd, k.encode() if isinstance(k, str) else k)
            if gap:
                self.read_for(gap)

    def exit_code(self, seconds=5):
        end = time.time() + seconds
        while time.time() < end:
            self.read_for(0.1)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.pid = 0
                return os.waitstatus_to_exitcode(status)
        self.fail("終わらない")

    def test_play_and_quit(self):
        self.spawn(80, 24)
        self.wait_text("DelveDown")
        self.send(["l", "j", "\x1b[C", "."], gap=0.05)
        self.send("?")
        self.wait_text("操作説明")
        self.send(["x", "i"], gap=0.1)
        self.wait_text("持ち物 (2/10)")
        self.send(["\x1b", "Q"], gap=0.1)
        self.wait_text("本当に終了しますか")
        self.send("y")
        self.assertEqual(self.exit_code(), 0)
        self.assertNotIn(b"Traceback", self.out)

    def test_too_small_then_resize(self):
        self.spawn(40, 10)
        self.wait_text("端末を広げてください")
        self.assertNotIn(b"DelveDown", self.out)
        self.resize(100, 30)
        self.wait_text("DelveDown")
        self.send(["Q", "y"], gap=0.1)
        self.assertEqual(self.exit_code(), 0)

    def test_random_keys(self):
        rng = random.Random(4)
        keys = list("hjklyubn.>id?Qnabc12346789x") + ["\x1b", "\x1b[A", "\x1b[B", "\x1b[D", "\x1b[C"]
        self.spawn(80, 24, seed=11)
        self.wait_text("DelveDown")
        for _ in range(1500):
            k = rng.choice(keys)
            if k == "Q":
                k = "Qn"  # 終了は確認で断る
            try:
                os.write(self.fd, k.encode())
            except OSError:
                break
            self.read_for(0.002)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:  # 死ぬかクリアして結果画面を抜けた
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                self.pid = 0
                break
        if self.pid:
            # 持ち物や説明を Esc で閉じてから終了する(結果画面なら Esc で抜ける)
            self.send(["\x1b", "Q", "y"], gap=0.2)
            self.assertEqual(self.exit_code(), 0)
        self.assertNotIn(b"Traceback", self.out)


@unittest.skipUnless(OK, "Linux の curses が要る")
class TestKeys(unittest.TestCase):
    def test_key_to_action(self):
        sys.path.insert(0, str(ROOT))
        from delvedown.ui import key_to_action
        self.assertEqual(key_to_action(ord("h")), ("move", -1, 0))
        self.assertEqual(key_to_action(ord("n")), ("move", 1, 1))
        self.assertEqual(key_to_action(curses.KEY_UP), ("move", 0, -1))
        self.assertEqual(key_to_action(curses.KEY_C1), ("move", -1, 1))
        self.assertEqual(key_to_action(ord("9")), ("move", 1, -1))
        self.assertEqual(key_to_action(ord("5")), ("wait",))
        self.assertEqual(key_to_action(ord(">")), ("descend",))
        self.assertIsNone(key_to_action(ord("z")))


if __name__ == "__main__":
    unittest.main()
