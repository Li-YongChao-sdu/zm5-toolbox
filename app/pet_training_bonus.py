"""升级期间的免费寿星/在线经验增益；只在本地判定失效后尝试，不付费。"""
import random,time

def active(info,key):
    buff=(info.get('buffs') or {}).get(str(key)) or {}
    end=buff.get('endTime')
    return bool(buff and end is not None and (end==-1 or end>time.time()*1000))

def ensure(flow,info,state,log):
    def checked(reply):
        if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):raise RuntimeError('免费经验增益失败：'+str(reply))
        return reply
    if not active(info,103001):
        used=int(((info.get('dungeon') or {}).get('200301') or {}).get('dailyCount',0))
        vip=int((info.get('vip') or {}).get('level',0));free=2 if vip>=3 else 1
        if used<free:
            from main_farm import _create
            rnd,created=_create(flow,200301)
            if created.get('consume'):raise RuntimeError('寿星入场出现额外消耗，停止')
            reply=checked(flow.request('scene.copyHandler.finishSingleCopy',{'win':1,'rnd':int(created['rnd'])^rnd,'star':3,'sceneBuffScore':100,'maxCombo':9,'killMonsterCnt':66,'useMagicWeaponCnt':0,'useBossCardCnt':0}))
            info.setdefault('dungeon',{})['200301']=reply.get('dungeon') or {'id':200301,'dailyCount':used+1}
            if reply.get('buffs') is not None:info['buffs']=reply['buffs']
            log('free_shouxing_bonus',{'dailyCount':info['dungeon']['200301'].get('dailyCount'),'buff':(info.get('buffs') or {}).get('103001')})
            if not active(info,103001):raise RuntimeError('寿星结算未确认经验增益，停止')
    if not active(info,103004) and not state.get('online_bonus_attempted'):
        state['online_bonus_attempted']=True
        reply=flow.request('scene.questHandler.commitQuest',{'qId':960001})
        if isinstance(reply,dict) and reply.get('code')==200 and not reply.get('error'):
            for give in reply.get('give') or []:
                if give.get('type')=='buff' and isinstance(give.get('data'),dict):info['buffs']=give['data']
            if reply.get('buffs') is not None:info['buffs']=reply['buffs']
            if not active(info,103004):raise RuntimeError('在线领奖成功但未确认经验增益，停止')
            log('free_online_bonus',{'buff':info['buffs'].get('103004')})
        else:
            log('online_bonus_unavailable',{'reply':reply,'note':'未领取到；不重试、不转付费，继续按实际经验计算局数'})
