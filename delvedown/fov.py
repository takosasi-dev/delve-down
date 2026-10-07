"""再帰シャドウキャスティングの視界(RogueBasin の Björn Bergström 版)。"""

from __future__ import annotations

# 8 つの八分円を、1つの走査を座標変換して回す
_MULT = (
    (1, 0, 0, -1, -1, 0, 0, 1),
    (0, 1, -1, 0, 0, -1, 1, 0),
    (0, 1, 1, 0, 0, -1, -1, 0),
    (1, 0, 0, 1, -1, 0, 0, -1),
)


def compute_fov(ox: int, oy: int, radius: int, blocks, w: int, h: int) -> set[tuple[int, int]]:
    """(ox, oy) から見えるマスの集合。blocks(x, y) は視線を遮るか(範囲外は呼ばない)。"""
    visible = {(ox, oy)}

    def opaque(x, y):
        return not (0 <= x < w and 0 <= y < h) or blocks(x, y)

    def cast(row, start, end, xx, xy, yx, yy):
        if start < end:
            return
        r2 = radius * radius
        new_start = start
        for j in range(row, radius + 1):
            dx, dy = -j - 1, -j
            blocked = False
            while dx <= 0:
                dx += 1
                x, y = ox + dx * xx + dy * xy, oy + dx * yx + dy * yy
                l_slope, r_slope = (dx - 0.5) / (dy + 0.5), (dx + 0.5) / (dy - 0.5)
                if start < r_slope:
                    continue
                if end > l_slope:
                    break
                if dx * dx + dy * dy <= r2 and 0 <= x < w and 0 <= y < h:
                    visible.add((x, y))
                if blocked:
                    if opaque(x, y):
                        new_start = r_slope
                    else:
                        blocked = False
                        start = new_start
                elif opaque(x, y) and j < radius:
                    blocked = True
                    cast(j + 1, start, l_slope, xx, xy, yx, yy)
                    new_start = r_slope
            if blocked:
                break

    for o in range(8):
        cast(1, 1.0, 0.0, _MULT[0][o], _MULT[1][o], _MULT[2][o], _MULT[3][o])
    return visible
