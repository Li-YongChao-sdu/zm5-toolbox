"""本批任务共用二级密码：不保存，不放入命令行。"""
PASSWORD_KEYS = ('ZM5_FOREST_CRYSTAL_PASSWORD', 'ZM5_ELITE_SELL_PASSWORD',
    'ZM5_STONE_SELL_PASSWORD', 'ZM5_CELEBRATION_PASSWORD',
    'ZM5_FASHION_SHOP_PASSWORD', 'ZM5_WHITE_DRAGON_PASSWORD',
    'ZM5_PET_UTILITY_PASSWORD', 'ZM5_UNION_WAREHOUSE_PASSWORD')

def prepare_launch(args, extra_env, password):
    args=list(args);env=dict(extra_env or {})
    if password:
        env.update({key:password for key in PASSWORD_KEYS})
        if any(str(a).replace(chr(92),'/').split('/')[-1]=='union_warehouse.py' for a in args):
            if '--password' in args:
                index=args.index('--password');del args[index:index+2]
    return args,env
