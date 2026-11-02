"""每日任务接取次数，与当前 VIP 配置中的 dailyTaskAccNum 对应。"""


def quota_from_info(info):
    vip = int(((info.get("vip") or {}).get("level")) or 0)
    used = int(((info.get("everyDaySetting") or {}).get("dailyQuestCnt")) or 0)
    limit = 3 if vip == 0 else 4 if vip <= 2 else 5
    return {"vip": vip, "used": used, "limit": limit,
            "remaining": max(0, limit - used)}
