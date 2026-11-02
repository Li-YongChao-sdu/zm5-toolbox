"""世界BOSS共用伤害采样。"""
import random

def sample_hurt(lower=100000, upper=500000):
    if lower < 0 or upper < lower:
        raise ValueError('伤害范围无效')
    return random.uniform(lower, upper)


def sample_expected_hurt(expected_dps):
    if expected_dps <= 0:
        raise ValueError('每秒期望伤害须大于0')
    return sample_hurt(expected_dps / 4, expected_dps * 7 / 4)


