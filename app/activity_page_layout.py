"""活动页只展示可用项目，保持后台任务变量完整。"""
PRIORITY=('RUN_ACT_XBAJIE','RUN_ACT_XBAILONG','RUN_ACT_XSHASENG','RUN_ACT_XYANGJIAN',
          'RUN_ACT_XWUKONG','RUN_ACT_XYAOYAO','RUN_ACT_XTANG','RUN_ACT_XLONG',
          'RUN_ACT_XINGTIAN','RUN_ACT_GM','RUN_ACT_FIGHT_GM','RUN_CLOUD_LADDER','RUN_CLIMB_HIGH','RUN_CELEBRATION')

def ordered_keys(keys,reason):
    positions={key:i for i,key in enumerate(keys)}
    priority={key:i for i,key in enumerate(PRIORITY)}
    return sorted(keys,key=lambda key:(bool(reason(key)),priority.get(key,len(PRIORITY)+positions[key]),positions[key]))
