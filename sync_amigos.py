"""Forward the saved snapshot to Amigos. This module never calls TibiaRelic."""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESTINATION = 'https://relichub.xyz/amigos/internal/boss-sync'
FIELDS = [p+s for p in ('lastDay','lastWeek','overall') for s in ('KilledPlayers','KilledByPlayers')]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def build_payload(root=ROOT):
    state = json.loads((root/'update-status.json').read_text(encoding='utf-8-sig'))
    phase = state.get('phase')
    if phase not in ('ok','retry','failed'):
        raise ValueError('Unknown collection status')
    stamp = state.get('checkedAt') if phase == 'ok' else state.get('failedAt')
    if not isinstance(stamp,str) or not isinstance(state.get('day'),str):
        raise ValueError('Missing source timestamps')
    payload = {'version':1,'kind':'status','phase':phase,'day':state['day'],'checkedAt':stamp}
    if phase == 'ok':
        data = json.loads((root/'killstatistics.json').read_text(encoding='utf-8-sig'))
        if not isinstance(data.get('entries'),list) or not data['entries']:
            raise ValueError('No validated snapshot available')
        seen=set()
        for row in data['entries']:
            name=row.get('raceName')
            if not isinstance(name,str) or not name.strip() or name.lower() in seen:
                raise ValueError('Invalid creature names')
            seen.add(name.lower())
            if any(type(row.get(k)) is not int or not 0 <= row[k] <= 9007199254740991 for k in FIELDS):
                raise ValueError('Invalid creature counts')
        date=data.get('lastDayUtc','')[:10]
        if date != state.get('dataDate','')[:10]:
            raise ValueError('Snapshot does not match collection status')
        payload.update(kind='snapshot',dataDate=date,entries=data['entries'])
    return payload

def send(payload,key):
    if not key or len(key)<48:
        raise ValueError('Missing delivery secret')
    body=json.dumps(payload,separators=(',',':'),ensure_ascii=True).encode()
    if len(body)>262144:
        raise ValueError('Saved snapshot exceeds delivery size limit')
    req=urllib.request.Request(DESTINATION,data=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'RelicHub-SavedSnapshot/1.0'},method='POST')
    opener=urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req,timeout=45) as response:
            result=json.loads(response.read(4096))
            if not result.get('ok'):
                raise ValueError('Delivery was not confirmed')
            return result
    except urllib.error.HTTPError as error:
        raise RuntimeError('Delivery rejected (HTTP '+str(error.code)+')') from None
    except urllib.error.URLError:
        raise RuntimeError('Delivery connection failed') from None

def main():
    try:
        payload=build_payload()
        if '--validate-only' in sys.argv:
            print('PASS: saved snapshot validated; no network request made.')
            return 0
        result=send(payload,os.environ.get('AMIGOS_SYNC_KEY',''))
        text='Amigos: saved data delivered; TibiaRelic API requests: 0. Duplicate: '+str(bool(result.get('duplicate')))
        print(text)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
                f.write('\n## Private delivery\n\n'+text+'\n')
        return 0
    except Exception as error:
        print('::warning::Amigos delivery pending. '+type(error).__name__+'. Saved source data was retained. No TibiaRelic request was made.')
        return 1

if __name__=='__main__':
    raise SystemExit(main())
