import os

from hypothesis import settings

# 決定性を守るため、CI では乱数を固定する(同じコミットなら同じ入力列)。
# 探索を広げたいときは HYPOTHESIS_PROFILE=explore で、毎回異なる入力を試せる。
settings.register_profile("ci", derandomize=True, max_examples=100, deadline=None)
settings.register_profile("explore", max_examples=1000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
