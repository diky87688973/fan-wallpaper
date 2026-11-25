"""校验依赖声明三处一致。

pyproject 的 [project].dependencies 是唯一来源，requirements.txt 是 pip 安装入口，
requirements.lock 是精确版本。三处漂移会让装出来的环境与声明不符。
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def package_name(spec: str) -> str:
    return re.split(r"[<>=!~\[ ]", spec, maxsplit=1)[0].lower().replace("_", "-")


def canonical(spec: str) -> str:
    return re.sub(r"\s+", "", spec).lower()


def read_specs(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"]["dependencies"]
    requirements = read_specs(ROOT / "requirements.txt")
    lock = read_specs(ROOT / "requirements.lock")

    problems: list[str] = []

    declared_set = {canonical(spec) for spec in declared}
    requirement_set = {canonical(spec) for spec in requirements}
    if declared_set != requirement_set:
        problems.append(
            "requirements.txt 与 pyproject.dependencies 不一致"
            f"\n      仅 pyproject 有：{sorted(declared_set - requirement_set)}"
            f"\n      仅 requirements.txt 有：{sorted(requirement_set - declared_set)}"
        )

    declared_names = {package_name(spec) for spec in declared}
    lock_names = {package_name(spec) for spec in lock}
    missing = declared_names - lock_names
    if missing:
        problems.append(f"requirements.lock 缺少声明包：{sorted(missing)}")

    if problems:
        print("依赖声明一致性检查未通过：")
        for item in problems:
            print(f"  - {item}")
        return 1

    print(f"依赖声明一致：{len(declared_names)} 个直接依赖，lock 覆盖 {len(lock_names)} 个包")
    return 0


if __name__ == "__main__":
    sys.exit(main())
