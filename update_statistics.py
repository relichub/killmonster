"""One API request per eligible run; retain the last valid snapshot on error."""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent
API = 'https://api.tibiarelic.com/api/killstatistics?worldname=relic'
FIELDS = [p+s for p in ('lastDay','lastWeek','overall') for s in ('KilledPlayers','KilledByPlayers')]
def now(): return datetime.now(timezone.utc)
def parse(value): return datetime.fromisoformat(value.replace('Z','+00:00'))
def validate(data, previous):
    if not isinstance(data,dict) or not isinstance(data.get('entries'),list) or not data['entries']: raise ValueError('Invalid or empty API response')
    dates=[parse(data[k]) for k in ('lastDayUtc','lastWeekStartUtc','lastWeekEndUtc')]
    if any(d.tzinfo is None for d in dates) or dates[1]>dates[2] or dates[0]>now(): raise ValueError('Invalid reporting dates')
    if previous and dates[0]<parse(previous['lastDayUtc']): raise ValueError('Refusing older reporting data')
    names=set()
    for row in data['entries']:
        name=row.get('raceName') if isinstance(row,dict) else None
        if not isinstance(name,str) or not name.strip() or name.lower() in names: raise ValueError('Invalid or duplicate creature')
        names.add(name.lower())
        if any(type(row.get(k)) is not int or row[k]<0 for k in FIELDS): raise ValueError('Invalid count')
    return data
def js(data): return json.dumps(data,separators=(',',':'),ensure_ascii=True).replace('<',chr(92)+'u003c')
def replace(html,key,value):
    html,count=re.subn(r'const '+key+r'=[^\n]*;',lambda _: 'const '+key+'='+js(value)+';',html,count=1)
    if count!=1: raise ValueError('Missing page constant '+key)
    return html
def save(html,state,data=None):
    html=replace(html,'UPDATE_STATUS',state)
    if data is not None:
        html=replace(html,'KILL_STATS',data);html=replace(html,'CHECKED_AT',state['checkedAt'])
    temp=ROOT/'index.tmp';temp.write_text(html,encoding='utf-8');temp.replace(ROOT/'index.html')
    (ROOT/'update-status.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
    if data is not None: (ROOT/'killstatistics.json').write_text(js(data)+'\n',encoding='utf-8')
def run(mode):
    timestamp=now();today=(timestamp-timedelta(hours=3)).date().isoformat()
    status=ROOT/'update-status.json';state=json.loads(status.read_text()) if status.exists() else {}
    if mode=='retry':
        if state.get('phase')!='retry' or state.get('day')!=today or state.get('attempts')!=1:
            print('No failed first attempt today. No API request.');return
        remaining=(parse(state['nextRetryAt'])-timestamp).total_seconds()
        if remaining>3900: raise ValueError('Unexpected retry time')
        if remaining>0:
            print('Waiting until one hour after first failure.',flush=True);time.sleep(remaining)
    elif mode=='daily' and state.get('day')==today and state.get('attempts',0)>=1:
        print('Daily attempt already recorded. No duplicate API request.');return
    elif mode not in ('daily','manual'): raise ValueError('Unknown mode')
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    previous=json.loads(re.search(r'const KILL_STATS=([^\n]*);',html)[1]);attempt=2 if mode=='retry' else 1
    try:
        request=urllib.request.Request(API,headers={'Accept':'application/json','User-Agent':'RelicHub-KillMonster/1.0'})
        with urllib.request.urlopen(request,timeout=45) as response:
            raw=response.read(5000001)
            if len(raw)>5000000: raise ValueError('API response too large')
            data=validate(json.loads(raw),previous)
    except Exception as exc:
        timestamp=now();state={'phase':'failed' if attempt==2 else 'retry','day':today,'attempts':attempt,'failedAt':timestamp.isoformat(),'nextRetryAt':(timestamp+timedelta(hours=1)).isoformat() if attempt==1 else None,'lastSuccessAt':state.get('checkedAt') or state.get('lastSuccessAt')}
        save(html,state);print('API failed; previous data retained. '+type(exc).__name__+': '+str(exc))
    else:
        state={'phase':'ok','day':today,'attempts':attempt,'checkedAt':now().isoformat(),'dataDate':data['lastDayUtc']}
        save(html,state,data);print('SUCCESS: '+str(len(data['entries']))+' records. API requests: 1.')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f: f.write('## Kill Monster update\n\nStatus: **'+state['phase']+'**\n\nAttempt: '+str(attempt)+'\n\nAPI requests: 1\n')
if __name__=='__main__': run(sys.argv[1] if len(sys.argv)>1 else 'manual')
