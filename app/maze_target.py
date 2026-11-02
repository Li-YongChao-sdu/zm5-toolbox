"""自建迷宫指定码解析、查询和统一单局结算。"""
import argparse,hashlib,json,re,time,math
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def decode_code(code):
    code=str(code).strip().lower()
    if re.fullmatch(r'\d+_\d+',code):uid,pos=map(int,code.split('_'))
    elif re.fullmatch(r'[0-9a-v]+[0-9]',code) and len(code)>=2:uid,pos=int(code[:-1],32),int(code[-1])
    else:raise ValueError('请输入游戏迷宫挑战码，或 UID_位置（例如3922097053_0）')
    if uid<=0 or not 0<=pos<=9:raise ValueError('迷宫UID或位置无效')
    return uid,pos

def encode_code(uid,pos):
    n=int(uid);s='';digits='0123456789abcdefghijklmnopqrstuv'
    while n:s=digits[n%32]+s;n//=32
    return (s or '0')+str(int(pos))

def query(flow,code):
    from free_maze_daily import _maze_data
    uid,pos=decode_code(code);d=_maze_data(flow,uid,pos)
    if not d.get('data'):raise ValueError('该迷宫没有可挑战的地图数据')
    fingerprint=hashlib.sha256(json.dumps({'data':d['data'],'name':d.get('name')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    attempts=int(d.get('inCnt') or 0);clears=int(d.get('outCnt') or 0)
    return {'uid':uid,'pos':pos,'id':d['_id'],'code':encode_code(uid,pos),'owner':d.get('username','未知'),'name':d.get('name',''),'attempts':attempts,'clears':clears,'fingerprint':fingerprint}

def wait_seconds(value):
    value=float(value)
    if not math.isfinite(value) or not 1<=value<=3600:raise ValueError('迷宫结算等待须为1～3600秒')
    return value

def play_once(flow,uid,pos,wait=30,report_dir=None):
    wait=wait_seconds(wait)
    from free_maze_daily import _checked
    def wallet():
        u=_checked(flow,'connector.roleHandler.getUserInfo',{}).get('user') or {}
        if any(u.get(k) is None for k in ('ticket','yuanbao')):raise ValueError('货币余额缺失')
        return {k:u[k] for k in ('ticket','yuanbao')}
    before=wallet();folder=Path(report_dir) if report_dir else ROOT/'maze_challenge_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json');r={'uid':int(uid),'pos':int(pos),'wallet_before':before,'phase':'begin_pending'}
    def save():path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        r['begin']=flow.request('scene.userMazeHandler.beginChallenge',{'uid':int(uid),'pos':int(pos)});r['phase']='begin_returned';save()
        if r['begin'].get('code')!=200 or r['begin'].get('error'):raise RuntimeError(str(r['begin']))
        if r['begin'].get('consume'):raise RuntimeError('迷宫开局出现非预期消耗，停止')
        print('[自建迷宫] 已开局，等待%s秒结算'%wait,flush=True);time.sleep(wait);r['phase']='end_pending';save()
        r['end']=flow.request('scene.userMazeHandler.endChallenge',{'type':'game pass','win':True});r['phase']='end_returned';save()
        if r['end'].get('code')!=200 or r['end'].get('error'):raise RuntimeError(str(r['end']))
        r['wallet_after']=wallet()
        if r['end'].get('consume') or before!=r['wallet_after']:raise RuntimeError('结算出现消耗或点券元宝变化，停止')
        r['phase']='verified';save();print('[自建迷宫] 结算成功，点券元宝未变化；记录：'+str(path),flush=True);return r['end']
    except Exception:
        save();print('[自建迷宫] 本局未确认完成，已停止且不会自动重发；记录：'+str(path),flush=True);raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--code',required=True);a=p.parse_args()
    from teacher_trial import connect
    from free_maze_daily import _task,_progress
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account['record_index']);f=None
    try:
        f,_=connect(account,slot);data=query(f,a.code)
        if data['uid']==int(account['uid']):raise ValueError('原客户端不支持挑战自己的迷宫，请选择其他玩家')
        task=_task(f);data.update(account=str(account.get('username','')),slot=slot,task_progress=_progress(task),task_status=(task or {}).get('status'))
        print('__MAZE_TARGET_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
    finally:
        if f:f.disconnect()

if __name__=='__main__':main()
