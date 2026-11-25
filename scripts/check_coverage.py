"""按模块校验覆盖率下限。

输入是 `pytest --cov-report=json:coverage.json` 生成的报告。
分母里没有出现的模块视为口径变更，直接失败，避免新文件被悄悄排除在外。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FLOORS = {
    "wallpaper/__init__.py": 100.0,
    "wallpaper/backend.py": 78.0,
    "wallpaper/config.py": 90.0,
    "wallpaper/desktop.py": 90.0,
    "wallpaper/media.py": 85.0,
    "wallpaper/protocol.py": 100.0,
    "wallpaper/scheduler.py": 85.0,
    "wallpaper/screen.py": 60.0,
    "wallpaper/tray.py": 90.0,
}


def main(argv: list[str]) -> int:
    report_path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    if not report_path.is_file():
        print(f"找不到覆盖率报告：{report_path}")
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))

    failures: list[str] = []
    seen: set[str] = set()
    for raw_name, info in sorted(report.get("files", {}).items()):
        name = Path(raw_name).as_posix()
        seen.add(name)
        floor = FLOORS.get(name)
        if floor is None:
            failures.append(f"{name} 未在 FLOORS 登记（覆盖率口径新增文件未纳入）")
            continue
        actual = float(info["summary"]["percent_covered"])
        mark = "OK  " if actual >= floor else "FAIL"
        print(f"{mark} {name:24} {actual:6.2f}%  >= {floor:5.1f}%")
        if actual < floor:
            failures.append(f"{name} {actual:.2f}% 低于下限 {floor:.1f}%")

    for name in sorted(set(FLOORS) - seen):
        failures.append(f"{name} 登记了下限但未出现在覆盖率报告中")

    if failures:
        print("\n覆盖率下限未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1

    print(f"\n{len(seen)} 个模块全部达到下限")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
