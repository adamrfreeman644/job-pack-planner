"""OpenRouteService optimisation and saved daily route plans."""
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json, re, socket
from flask import jsonify, request

ORS='https://api.openrouteservice.org'; DAY=re.compile(r'^\d{4}-\d{2}-\d{2}$')

class RouteError(Exception):
 def __init__(self,message,status=400): super().__init__(message); self.status=status

def _read_json(req,limit=4*1024*1024):
 try:
  with urlopen(req,timeout=25) as response:
   raw=response.read(limit+1)
   if len(raw)>limit: raise RouteError('The routing response was too large.',502)
   return json.loads(raw)
 except HTTPError as error:
  try: detail=json.loads(error.read()).get('error',{}).get('message','')
  except Exception: detail=''
  if error.code in {401,403}: raise RouteError('OpenRouteService refused the API key. Check the key in Settings.',502)
  if error.code==429: raise RouteError('The OpenRouteService free allowance is temporarily exhausted. Try again later.',429)
  raise RouteError(detail or 'OpenRouteService could not calculate this route.',502)
 except (URLError,socket.timeout,TimeoutError,OSError,ValueError): raise RouteError('OpenRouteService could not be reached. Try again shortly.',502)

def _post(path,key,body,accept='application/json'):
 return _read_json(Request(ORS+path,data=json.dumps(body).encode(),method='POST',headers={'Authorization':key,'Content-Type':'application/json','Accept':accept}))

def _geocode(key,text,db):
 normal=' '.join(str(text).split()); cache_key='route_geocode:'+sha256(normal.lower().encode()).hexdigest()
 c=db(); row=c.execute('SELECT v FROM settings WHERE k=?',(cache_key,)).fetchone(); c.close()
 if row:
  try: return json.loads(row['v'])
  except (ValueError,TypeError): pass
 query=urlencode({'api_key':key,'text':normal,'boundary.country':'GB','size':1})
 data=_read_json(Request(ORS+'/geocode/search?'+query,headers={'Accept':'application/json'})); features=data.get('features',[]) if isinstance(data,dict) else []
 if not features or not isinstance(features[0].get('geometry',{}).get('coordinates'),list): raise RouteError(f'Could not locate: {normal}',422)
 coords=features[0]['geometry']['coordinates'][:2]
 c=db(); c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',(cache_key,json.dumps(coords))); c.commit(); c.close(); return coords

def _haversine(a,b):
 lon1,lat1,lon2,lat2=map(radians,[a[0],a[1],b[0],b[1]]); dlon, dlat=lon2-lon1,lat2-lat1
 value=sin(dlat/2)**2+cos(lat1)*cos(lat2)*sin(dlon/2)**2
 return 12742*asin(min(1,sqrt(value)))

def _least_driving(key,start,end,items):
 if len(items)<2: return list(items)
 data=_post('/optimization',key,{'jobs':[{'id':i+1,'location':item['coordinates']} for i,item in enumerate(items)],'vehicles':[{'id':1,'profile':'driving-car','start':start,'end':end}]})
 routes=data.get('routes',[]) if isinstance(data,dict) else []
 if not routes: raise RouteError('OpenRouteService did not return an optimised route.',422)
 ids=[step.get('job') for step in routes[0].get('steps',[]) if step.get('type')=='job']
 if len(ids)!=len(items): raise RouteError('OpenRouteService returned an incomplete stop order.',502)
 return [items[index-1] for index in ids]

def _nearest_order(start,items):
 remaining=list(items); ordered=[]; current=start
 while remaining:
  item=min(remaining,key=lambda value:_haversine(current,value['coordinates']))
  remaining.remove(item); ordered.append(item); current=item['coordinates']
 return ordered

def _keep_locked(original,proposed,locked_keys):
 if not locked_keys: return proposed
 locked_slots={i:item for i,item in enumerate(original) if item['key'] in locked_keys}; remaining=[item for item in proposed if item['key'] not in locked_keys]; result=[]
 for i in range(len(original)): result.append(locked_slots[i] if i in locked_slots else remaining.pop(0))
 return result

def _directions(key,home,ordered):
 data=_post('/v2/directions/driving-car/geojson',key,{'coordinates':[home]+[item['coordinates'] for item in ordered]+[home],'instructions':False,'units':'mi'},'application/geo+json')
 features=data.get('features',[]) if isinstance(data,dict) else []
 if not features: raise RouteError('No complete driving route was found for these stops.',422)
 feature=features[0]; props=feature.get('properties',{}); route_summary=props.get('summary',{}); segments=props.get('segments',[]); legs=[]
 for i,segment in enumerate(segments):
  legs.append({'from_key':'home' if i==0 else ordered[i-1]['key'],'to_key':'home' if i>=len(ordered) else ordered[i]['key'],'duration_minutes':max(1,round(float(segment.get('duration',0))/60)),'distance_miles':round(float(segment.get('distance',0)),1)})
 return {'legs':legs,'duration_minutes':max(1,round(float(route_summary.get('duration',0))/60)),'distance_miles':round(float(route_summary.get('distance',0)),1),'geometry':feature.get('geometry',{}).get('coordinates',[])}

def register_routes(app,db):
 def values():
  c=db(); out={row['k']:row['v'] for row in c.execute("SELECT k,v FROM settings WHERE k IN ('home_address','openrouteservice_api_key')")}; c.close(); return out
 def body():
  data=request.get_json(silent=True) if request.is_json else None
  if not isinstance(data,dict): raise RouteError('Use the planner to submit this request.',415)
  return data
 def reply(fn):
  try: response=app.make_response(fn())
  except RouteError as error: response=jsonify(error=str(error)); response.status_code=error.status
  response.headers['Cache-Control']='no-store'; response.headers['X-Content-Type-Options']='nosniff'; return response
 def saved_plan(day):
  c=db(); row=c.execute('SELECT v FROM settings WHERE k=?',('route_plan:'+day,)).fetchone(); c.close()
  if not row: return {'day':day,'stops':[],'items':[]}
  try: return json.loads(row['v'])
  except (ValueError,TypeError): return {'day':day,'stops':[],'items':[]}

 @app.get('/api/route/settings')
 def route_settings(): return reply(lambda: jsonify(home_address=values().get('home_address',''),has_api_key=bool(values().get('openrouteservice_api_key')),provider='OpenRouteService'))

 @app.post('/api/route/settings')
 def save_route_settings():
  def action():
   data=body(); home=str(data.get('home_address','')).strip(); key=str(data.get('api_key','')).strip()
   if len(home)>500 or len(key)>4096 or any(ord(ch)<32 for ch in key): raise RouteError('The route settings are invalid.')
   c=db(); c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',('home_address',home))
   if data.get('clear_api_key'): c.execute("DELETE FROM settings WHERE k='openrouteservice_api_key'")
   elif key: c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',('openrouteservice_api_key',key))
   c.execute("DELETE FROM settings WHERE k='google_routes_api_key'"); c.commit(); c.close(); current=values()
   return jsonify(home_address=current.get('home_address',''),has_api_key=bool(current.get('openrouteservice_api_key')),provider='OpenRouteService')
  return reply(action)

 @app.get('/api/route/day/<day>')
 def get_day_route(day):
  def action():
   if not DAY.fullmatch(day): raise RouteError('Invalid date.')
   return jsonify(saved_plan(day))
  return reply(action)

 @app.post('/api/route/plan')
 def plan_route():
  def action():
   data=body(); day=str(data.get('day','')); raw_ids=data.get('job_ids',[]); raw_stops=data.get('stops',[]); mode=data.get('mode','least')
   if not DAY.fullmatch(day) or mode not in {'least','furthest'} or not isinstance(raw_ids,list) or not isinstance(raw_stops,list): raise RouteError('The route request is invalid.')
   if not raw_ids and not raw_stops: raise RouteError('Add at least one job or pickup stop.')
   if len(raw_ids)+len(raw_stops)>25: raise RouteError('A route can contain up to 25 stops.')
   try: ids=[int(value) for value in raw_ids]
   except (TypeError,ValueError): raise RouteError('The selected jobs are invalid.')
   current=values(); home_text=current.get('home_address','').strip(); key=current.get('openrouteservice_api_key','').strip()
   if not home_text: raise RouteError('Add your home or start address in Settings first.',409)
   if not key: raise RouteError('Add a free OpenRouteService API key in Settings first.',409)
   c=db(); placeholders=','.join('?' for _ in ids); rows=list(c.execute(f'SELECT * FROM jobs WHERE id IN ({placeholders})',ids)) if ids else []; c.close(); by_id={row['id']:row for row in rows}
   if len(by_id)!=len(ids): raise RouteError('One of these jobs no longer exists.',404)
   job_items=[]
   for job_id in ids:
    row=by_id[job_id]; details=json.loads(row['details'] or '{}'); address=(details.get('Site Address') or row['postcode'] or '').strip()
    if not address: raise RouteError(f"Job {row['job_no']} has no address.",422)
    job_items.append({'key':f'job:{job_id}','type':'job','id':job_id,'label':row['job_no']+' · '+row['title'],'address':address})
   clean_stops=[]
   for index,stop in enumerate(raw_stops):
    if not isinstance(stop,dict): raise RouteError('A pickup or drop-off is invalid.')
    stop_id=re.sub(r'[^A-Za-z0-9_-]','',str(stop.get('id','')))[:80] or f'collection-{index+1}'; label=str(stop.get('label','')).strip()[:120]; address=str(stop.get('address','')).strip()[:500]
    if not label or not address: raise RouteError('Each colleague collection needs a name and address.')
    clean={'id':stop_id,'type':'collection','label':label,'address':address}; clean_stops.append(clean)
   home=_geocode(key,home_text,db)
   for item in job_items: item['coordinates']=_geocode(key,item['address'],db)
   collections=[]
   for stop in clean_stops:
    coordinates=_geocode(key,stop['address'],db); collections.append({**stop,'coordinates':coordinates})
   pickups=_nearest_order(home,[{'key':'pickup:'+stop['id'],'type':'pickup','id':stop['id'],'label':stop['label'],'address':stop['address'],'coordinates':stop['coordinates']} for stop in collections])
   dropoffs=[{'key':'dropoff:'+stop['id'],'type':'dropoff','id':stop['id'],'label':stop['label'],'address':stop['address'],'coordinates':stop['coordinates']} for stop in reversed(pickups)]
   job_start=pickups[-1]['coordinates'] if pickups else home; job_end=dropoffs[0]['coordinates'] if dropoffs else home
   proposed=sorted(job_items,key=lambda item:_haversine(home,item['coordinates']),reverse=True) if mode=='furthest' else _least_driving(key,job_start,job_end,job_items)
   locked={f'job:{int(value)}' for value in data.get('locked_ids',[]) if str(value).isdigit()}; ordered_jobs=_keep_locked(job_items,proposed,locked); ordered=pickups+ordered_jobs+dropoffs; route=_directions(key,home,ordered)
   public_items=[{k:v for k,v in item.items() if k!='coordinates'} for item in ordered]
   return jsonify(day=day,mode=mode,items=public_items,stops=clean_stops,**route)
  return reply(action)

 @app.post('/api/route/apply')
 def apply_route():
  def action():
   data=body(); day=str(data.get('day','')); items=data.get('items',[]); stops=data.get('stops',[])
   if not DAY.fullmatch(day) or not isinstance(items,list) or not isinstance(stops,list): raise RouteError('The saved route is invalid.')
   job_ids=[]
   for item in items:
    if isinstance(item,dict) and item.get('type')=='job':
     try: job_ids.append(int(item['id']))
     except (KeyError,TypeError,ValueError): raise RouteError('The saved job order is invalid.')
   c=db()
   for position,job_id in enumerate(job_ids): c.execute('UPDATE jobs SET position=? WHERE id=? AND day=?',(position,job_id,day))
   saved={'day':day,'mode':data.get('mode','least'),'items':items,'stops':stops,'duration_minutes':data.get('duration_minutes',0),'distance_miles':data.get('distance_miles',0),'legs':data.get('legs',[]),'geometry':data.get('geometry',[])}
   c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',('route_plan:'+day,json.dumps(saved))); c.commit(); c.close()
   return jsonify(ok=True,ordered_ids=job_ids)
  return reply(action)
