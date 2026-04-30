"""project_name 撞名时的随机后缀生成。

slug 由调用方（agent / UI）自己生成，scheduler 只在 INSERT 冲突时挂 `-<4 随机字母>`。
SDK 的 ``aijuicer_sdk.slug.slugify_idea`` 提供了一个默认实现；caller 想自定义可以不用。
"""

from __future__ import annotations

import random
import string


def random_suffix(n: int = 4) -> str:
    """生成 n 位小写字母随机后缀。"""
    return "".join(random.choices(string.ascii_lowercase, k=n))
