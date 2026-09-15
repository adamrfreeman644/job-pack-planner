from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
from datetime import datetime
import sqlite3, xml.etree.ElementTree as ET, io, re, json, os, threading
import requests, msal
from apscheduler.schedulers.background import BackgroundScheduler
from zoneinfo import ZoneInfo

app=Flask(__name__)
DATA=Path('/data'); DATA.mkdir(exist_ok=True)
DB=DATA/'planner.db'; MASTER=DATA/'master.xml'
TOKEN_CACHE=DATA/'ms-token-cache.json'; OUTLOOK={'state':'disconnected','message':'','flow':None}
SCOPES=['Mail.Read']

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,job_no TEXT UNIQUE,day TEXT,booking_xml TEXT,title TEXT,postcode TEXT,start TEXT,finish TEXT,position INTEGER,details TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)'); c.commit(); return c

def postcode(s):
 m=re.search(r'\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b',s.upper()); return m.group(1) if m else ''

def fields(record):
 out={}
 for f in record.findall('field'): out.setdefault(f.get('name'),[]).append((f.text or '').strip())
 return out

def first(d,*names):
 for n in names:
  if d.get(n) and d[n][0]: return d[n][0]
 return ''

def import_booking(raw):
 root=ET.fromstring(raw); rec=root.find('record')
 if rec is None: return None
 d=fields(rec); j=first(d,'Job No.','Job Number'); date=first(d,'Date')
 if not j: return None
 try: day=datetime.strptime(date,'%d-%m-%Y').date().isoformat()
 except: day=datetime.now().date().isoformat()
 addr=first(d,'Site Address'); company=first(d,'Company'); work=first(d,'Work Required'); title=(addr.splitlines()[0] if addr else company) or j
 details=json.dumps({k:first(d,k) for k in ['Booking ID','Job No.','Division','Date','Company','Cust. Ref.','Site Address','Site Contact','Site Phone','Service','Work Required','A&A Resources','A&A Representative']})
 c=db(); pos=c.execute('SELECT COALESCE(MAX(position),0)+1 FROM jobs WHERE day=?',(day,)).fetchone()[0]
 c.execute('INSERT OR REPLACE INTO jobs(job_no,day,booking_xml,title,postcode,start,finish,position,details) VALUES(?,?,?,?,?,?,?,?,?)',(j,day,raw.decode('utf-8','replace'),title,postcode(addr),'09:00','10:00',pos,details)); c.commit(); c.close(); return j

def token_cache():
 cache=msal.SerializableTokenCache()
 if TOKEN_CACHE.exists(): cache.deserialize(TOKEN_CACHE.read_text())
 return cache

def save_cache(cache):
 if cache.has_state_changed:
  TOKEN_CACHE.write_text(cache.serialize()); os.chmod(TOKEN_CACHE,0o600)

def ms_app(cache):
 cid=os.getenv('MS_CLIENT_ID','').strip(); tenant=os.getenv('MS_TENANT_ID','organizations').strip()
 return msal.PublicClientApplication(cid,authority=f'https://login.microsoftonline.com/{tenant}',token_cache=cache) if cid else None

def access_token(interactive=False):
 cache=token_cache(); appx=ms_app(cache)
 if not appx: return None
 accounts=appx.get_accounts(); result=appx.acquire_token_silent(SCOPES,account=accounts[0]) if accounts else None
 save_cache(cache); return result.get('access_token') if result else None

def pull_outlook():
 token=access_token();
 if not token: return {'connected':False,'added':[]}
 headers={'Authorization':f'Bearer {token}'}
 url='https://graph.microsoft.com/v1.0/me/messages?$top=50&$filter=hasAttachments eq true&$select=id,subject,receivedDateTime,hasAttachments'
 messages=requests.get(url,headers=headers,timeout=30).json().get('value',[]); added=[]
 for m in messages:
  ats=requests.get(f"https://graph.microsoft.com/v1.0/me/messages/{m['id']}/attachments",headers=headers,timeout=30).json().get('value',[])
  for a in ats:
   if a.get('name','').lower().endswith('.xml') and a.get('contentBytes'):
    import base64
    try:
     j=import_booking(base64.b64decode(a['contentBytes']));
     if j: added.append(j)
    except Exception: pass
 OUTLOOK.update(state='connected',message=f'{len(added)} booking(s) checked')
 return {'connected':True,'added':added}

@app.get('/')
def home(): return render_template('index.html')

@app.get('/api/state')
def state():
 c=db(); jobs=[dict(x) for x in c.execute('SELECT * FROM jobs ORDER BY day,position,id')]
 st={x['k']:x['v'] for x in c.execute('SELECT * FROM settings')}; c.close()
 return jsonify(jobs=jobs,settings=st,master=MASTER.exists())

@app.post('/api/import')
def import_xml():
 added=[]
 for file in request.files.getlist('files'):
  try:
   j=import_booking(file.read())
   if j: added.append(j)
  except Exception: pass
 return jsonify(added=added)

@app.post('/api/outlook/start')
def outlook_start():
 cache=token_cache(); appx=ms_app(cache)
 if not appx: return jsonify(state='not_configured',message='MS_CLIENT_ID has not been configured.'),400
 flow=appx.initiate_device_flow(scopes=SCOPES)
 if 'user_code' not in flow: return jsonify(state='error',message=flow.get('error_description','Microsoft login could not start.')),400
 OUTLOOK.update(state='waiting',message=flow['message'],flow=flow)
 def finish():
  result=appx.acquire_token_by_device_flow(flow)
  save_cache(cache); desc=result.get('error_description','')
  if 'admin' in desc.lower() or 'aadsts65001' in desc.lower() or 'aadsts90094' in desc.lower(): OUTLOOK.update(state='admin_required',message='Microsoft requires administrator approval. Connection stopped immediately.',flow=None)
  elif result.get('access_token'): OUTLOOK.update(state='connected',message='Outlook connected.',flow=None); pull_outlook()
  else: OUTLOOK.update(state='error',message=desc or 'Microsoft login was not completed.',flow=None)
 threading.Thread(target=finish,daemon=True).start()
 return jsonify(state='waiting',user_code=flow['user_code'],verification_uri=flow['verification_uri'],message=flow['message'])

@app.get('/api/outlook/status')
def outlook_status(): return jsonify(state=OUTLOOK['state'],message=OUTLOOK['message'],connected=bool(access_token()))

@app.post('/api/outlook/pull')
def outlook_pull():
 try: return jsonify(pull_outlook())
 except Exception as e: return jsonify(error='Outlook check failed without importing any messages.'),502

@app.post('/api/master')
def master():
 raw=request.files['file'].read(); root=ET.fromstring(raw)
 rec=root.find('record')
 if rec is None: return jsonify(error='No record found'),400
 for f in rec.findall('field'): f.text=''
 ET.ElementTree(root).write(MASTER,encoding='windows-1252',xml_declaration=True)
 return jsonify(ok=True)

@app.post('/api/save')
def save():
 body=request.json; c=db()
 for i,j in enumerate(body['jobs']): c.execute('UPDATE jobs SET day=?,start=?,finish=?,position=? WHERE id=?',(body['day'],j['start'],j['finish'],i,j['id']))
 for k,v in body.get('settings',{}).items(): c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',(k,str(v)))
 c.commit(); c.close(); return jsonify(ok=True)

def set_occurrences(rec,name,value):
 for f in rec.findall('field'):
  if f.get('name')==name: f.text=str(value or '')

@app.get('/api/export/<int:job_id>')
def export(job_id):
 if not MASTER.exists(): return jsonify(error='Upload a completed reference XML in Settings first'),400
 c=db(); job=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone(); jobs=list(c.execute('SELECT * FROM jobs WHERE day=? ORDER BY position,id',(job['day'],))); st={x['k']:x['v'] for x in c.execute('SELECT * FROM settings')}; c.close()
 i=next(n for n,x in enumerate(jobs) if x['id']==job_id); prev=st.get('leave_home','') if i==0 else jobs[i-1]['finish']; nxt=st.get('return_home','') if i==len(jobs)-1 else jobs[i+1]['start']
 root=ET.parse(MASTER).getroot(); rec=root.find('record'); d=json.loads(job['details']); rec.set('name',f"{job['job_no']} {job['day'].replace('-','/')}")
 mapping={'Booking ID':d.get('Booking ID'),'Job No.':job['job_no'],'Job Number':job['job_no'],'Company':d.get('Company'),'Front Cover client':d.get('Company'),'Cust. Ref.':d.get('Cust. Ref.'),'Work Order':d.get('Cust. Ref.'),'Site Address':d.get('Site Address'),'Site Contact':d.get('Site Contact'),'Site Phone':d.get('Site Phone'),'Service':d.get('Service'),'Work Required':d.get('Work Required'),'Depart Time':prev,'Arrive Site':job['start'],'Depart Site':job['finish'],'Arrive Next':nxt,'A&A Resources':st.get('resources','Adam Freeman, Peter Bennett, RA25 TLZ'),'A&A Representative':st.get('representative','Adam Freeman'),'Lead Engineer':st.get('lead','Adam'),'Engineer 2':st.get('engineer2','Pete'),'RAMS Number ':st.get('rams','010203')}
 for k,v in mapping.items(): set_occurrences(rec,k,v)
 for k in ['Do you have the correct documentation or permit for the task?','Do you understand the task?','Are you authorised & competent to carry out the task?','Are isolations in place?','Do you have the correct PPE and tools for the job?','Are calibrated items in date?','Have all vehicle checks been carried out?']: set_occurrences(rec,k,'Yes')
 set_occurrences(rec,'Are all  electrical equipment PAT test in date?','N/A'); set_occurrences(rec,'Vehicle logged','N/A'); set_occurrences(rec,'Any lessons for next time?','No'); set_occurrences(rec,'Has the work created any new hazards?','No')
 buf=io.BytesIO(); ET.ElementTree(root).write(buf,encoding='windows-1252',xml_declaration=True); buf.seek(0)
 return send_file(buf,mimetype='text/xml',as_attachment=True,download_name=f"{job['job_no']}-prepared.xml")

@app.delete('/api/jobs/<int:job_id>')
def delete(job_id):
 c=db(); c.execute('DELETE FROM jobs WHERE id=?',(job_id,)); c.commit(); c.close(); return jsonify(ok=True)

if __name__=='__main__': app.run(host='0.0.0.0',port=1976)
