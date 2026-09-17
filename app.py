from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from pathlib import Path
from datetime import datetime
import sqlite3, xml.etree.ElementTree as ET, io, re, json, os, math
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

app=Flask(__name__)
DATA=Path(os.getenv('JOB_PACK_DATA','/data')); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'planner.db'; MASTER=DATA/'master.xml'
SHARE=Path(os.getenv('JOB_PACK_SHARE','/imports'))

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
 columns=[row['name'] for row in c.execute('PRAGMA table_info(jobs)')]
 if not columns:
  c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,booking_key TEXT UNIQUE,job_no TEXT,day TEXT,booking_xml TEXT,title TEXT,postcode TEXT,start TEXT,finish TEXT,position INTEGER,details TEXT)')
 elif 'booking_key' not in columns:
  c.execute('ALTER TABLE jobs RENAME TO jobs_legacy')
  c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,booking_key TEXT UNIQUE,job_no TEXT,day TEXT,booking_xml TEXT,title TEXT,postcode TEXT,start TEXT,finish TEXT,position INTEGER,details TEXT)')
  c.execute("INSERT INTO jobs(id,booking_key,job_no,day,booking_xml,title,postcode,start,finish,position,details) SELECT id,job_no || ':' || day,job_no,day,booking_xml,title,postcode,start,finish,position,details FROM jobs_legacy")
  c.execute('DROP TABLE jobs_legacy')
 c.execute('CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT)'); c.execute('CREATE TABLE IF NOT EXISTS job_materials(job_id INTEGER PRIMARY KEY,materials TEXT NOT NULL DEFAULT \'\')'); c.commit(); return c

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

def assigned_engineers(resource_text):
 parts=[x.strip() for x in re.split(r'[,;\n]+',resource_text or '') if x.strip()]
 vehicle=re.compile(r'^[A-Z]{2}\d{2}\s*[A-Z]{3}$',re.I)
 people=[x for x in parts if not vehicle.match(x) and re.search(r'[A-Za-z].+\s+[A-Za-z]',x)]
 short=[]
 preferred={'peter':'Pete'}
 for person in people[:2]:
  first_name=person.split()[0]
  short.append(preferred.get(first_name.lower(),first_name))
 return short

def nearest_ae(site_postcode):
 fallback='Hospital'; clean=re.sub(r'\s+','',site_postcode or '').upper()
 if not clean: return fallback
 cache_key=f'hospital:{clean}'; c=db(); row=c.execute('SELECT v FROM settings WHERE k=?',(cache_key,)).fetchone(); c.close()
 if row: return row['v']
 try:
  headers={'User-Agent':'JobPackPlanner/1.0'}
  geo=json.loads(urlopen(Request(f'https://api.postcodes.io/postcodes/{quote(clean)}',headers=headers),timeout=6).read())['result']
  lat=float(geo['latitude']); lon=float(geo['longitude'])
  query=f'''[out:json][timeout:12];(
   nwr["amenity"="hospital"]["emergency"="yes"](around:80000,{lat},{lon});
   nwr["healthcare"="hospital"]["emergency"="yes"](around:80000,{lat},{lon});
   nwr["emergency"="emergency_ward_entrance"](around:80000,{lat},{lon});
  );out center tags;'''
  req=Request('https://overpass-api.de/api/interpreter',data=urlencode({'data':query}).encode(),headers={**headers,'Content-Type':'application/x-www-form-urlencoded'})
  elements=json.loads(urlopen(req,timeout=15).read()).get('elements',[]); choices=[]
  for element in elements:
   tags=element.get('tags',{}); name=tags.get('name') or tags.get('operator')
   point=element.get('center',element); elat=point.get('lat'); elon=point.get('lon')
   if not name or elat is None or elon is None: continue
   a=math.radians(float(elat)-lat); b=math.radians(float(elon)-lon)
   h=math.sin(a/2)**2+math.cos(math.radians(lat))*math.cos(math.radians(float(elat)))*math.sin(b/2)**2
   distance=6371*2*math.asin(min(1,math.sqrt(h))); hospital_postcode=tags.get('addr:postcode','').strip()
   choices.append((distance,f'{name}, {hospital_postcode}' if hospital_postcode else name))
  if not choices: return fallback
  value=min(choices,key=lambda item:item[0])[1]; c=db(); c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',(cache_key,value)); c.commit(); c.close(); return value
 except Exception: return fallback

def booking_days(d):
 days=[]
 for value in d.get('Date',[]):
  try: day=datetime.strptime(value,'%d-%m-%Y').date().isoformat()
  except ValueError: continue
  if day not in days: days.append(day)
 return days or [datetime.now().date().isoformat()]

def import_booking(raw):
 root=ET.fromstring(raw); rec=root.find('record')
 if rec is None: return []
 d=fields(rec); j=first(d,'Job No.','Job Number')
 if not j: return []
 addr=first(d,'Site Address'); company=first(d,'Company'); title=(addr.splitlines()[0] if addr else company) or j
 booking_id=first(d,'Booking ID')
 details=json.dumps({k:first(d,k) for k in ['Booking ID','Job No.','Division','Date','Company','Cust. Ref.','Site Address','Site Contact','Site Phone','Service','Work Required','A&A Resources','A&A Representative']})
 c=db(); added=[]
 for day in booking_days(d):
  booking_key=f'{j}:{booking_id or "visit"}:{day}'
  existing=c.execute('SELECT id FROM jobs WHERE booking_key=?',(booking_key,)).fetchone()
  if existing:
   c.execute('UPDATE jobs SET booking_xml=?,title=?,postcode=?,details=? WHERE booking_key=?',(raw.decode('utf-8','replace'),title,postcode(addr),details,booking_key))
  else:
   pos=c.execute('SELECT COALESCE(MAX(position),0)+1 FROM jobs WHERE day=?',(day,)).fetchone()[0]
   c.execute('INSERT INTO jobs(booking_key,job_no,day,booking_xml,title,postcode,start,finish,position,details) VALUES(?,?,?,?,?,?,?,?,?,?)',(booking_key,j,day,raw.decode('utf-8','replace'),title,postcode(addr),'08:00','16:00',pos,details))
  added.append(j)
 c.commit(); c.close(); return added

def install_master(raw):
 root=ET.fromstring(raw); rec=root.find('record')
 if rec is None or len(rec.findall('field'))<100: raise ValueError('This is not a complete Job Pack XML template.')
 for f in rec.findall('field'): f.text=''
 ET.ElementTree(root).write(MASTER,encoding='windows-1252',xml_declaration=True)

def scan_share_folder():
 added=[]; errors=[]; template_name=''; templates=[]
 paths=sorted(SHARE.rglob('*.xml')) if SHARE.exists() else []
 for path in paths:
  try:
   raw=path.read_bytes(); root=ET.fromstring(raw); rec=root.find('record')
   if rec is None: raise ValueError('No record found')
   if len(rec.findall('field'))>=100: templates.append((path.stat().st_mtime,path,raw))
   else:
    jobs=import_booking(raw)
    if jobs: added.extend(jobs)
    else: errors.append(f'{path.name}: not a recognised booking')
  except Exception: errors.append(f'{path.name}: could not be read')
 if templates:
  _,path,raw=max(templates,key=lambda item:item[0]); install_master(raw); template_name=str(path.relative_to(SHARE))
 return {'bookings':added,'template':template_name,'errors':errors,'path':str(SHARE)}

def share_inventory():
 bookings=0; templates=0; errors=0
 for path in SHARE.rglob('*.xml') if SHARE.exists() else []:
  try:
   rec=ET.parse(path).getroot().find('record'); count=len(rec.findall('field')) if rec is not None else 0
   if count>=100: templates+=1
   elif count: bookings+=1
   else: errors+=1
  except Exception: errors+=1
 return bookings,templates,errors

@app.get('/')
def home(): return render_template('index.html')

@app.get('/sw.js')
def service_worker():
 response=send_from_directory(app.static_folder,'sw.js',mimetype='application/javascript')
 response.headers['Service-Worker-Allowed']='/'
 return response

@app.get('/settings')
def settings_page(): return render_template('settings.html')

@app.get('/api/state')
def state():
 c=db(); jobs=[dict(x) for x in c.execute('SELECT jobs.*,COALESCE(job_materials.materials,\'\') AS materials FROM jobs LEFT JOIN job_materials ON job_materials.job_id=jobs.id ORDER BY jobs.day,jobs.position,jobs.id')]
 st={x['k']:x['v'] for x in c.execute('SELECT * FROM settings') if not x['k'].startswith('immich_') and not x['k'].startswith('route_') and x['k'] not in {'google_routes_api_key','openrouteservice_api_key'}}; c.close()
 return jsonify(jobs=jobs,settings=st,master=MASTER.exists())

@app.post('/api/import')
def import_xml():
 added=[]
 for file in request.files.getlist('files'):
  try:
   jobs=import_booking(file.read())
   if jobs: added.extend(jobs)
  except Exception: pass
 return jsonify(added=added)

@app.post('/api/master')
def master():
 try: install_master(request.files['file'].read()); return jsonify(ok=True)
 except Exception as e: return jsonify(error=str(e) or 'Could not read template'),400

@app.get('/api/folder/status')
def folder_status():
 bookings,templates,errors=share_inventory()
 return jsonify(path=str(SHARE),available=SHARE.exists(),bookings=bookings,templates=templates,errors=errors,master=MASTER.exists())

@app.post('/api/folder/scan')
def folder_scan(): return jsonify(scan_share_folder())

@app.post('/api/jobs/<int:job_id>/materials')
def save_materials(job_id):
 body=request.get_json(silent=True) or {}; materials=str(body.get('materials','')).strip()
 if len(materials)>2000: return jsonify(error='Materials text is too long.'),400
 c=db()
 if not c.execute('SELECT 1 FROM jobs WHERE id=?',(job_id,)).fetchone(): c.close(); return jsonify(error='Job not found.'),404
 c.execute('INSERT OR REPLACE INTO job_materials(job_id,materials) VALUES(?,?)',(job_id,materials)); c.commit(); c.close()
 return jsonify(ok=True,materials=materials)

@app.post('/api/save')
def save():
 body=request.json; c=db()
 for i,j in enumerate(body['jobs']): c.execute('UPDATE jobs SET day=?,start=?,finish=?,position=? WHERE id=?',(body['day'],j['start'],j['finish'],i,j['id']))
 for k,v in body.get('settings',{}).items():
  if k in {'leave_home','return_home','resources','rams'}: c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',(k,str(v)))
 c.commit(); c.close(); return jsonify(ok=True)

def set_occurrences(rec,name,value):
 for f in rec.findall('field'):
  if f.get('name')==name: f.text=str(value or '')

def set_occurrence_values(rec,name,values):
 matches=[f for f in rec.findall('field') if f.get('name')==name]
 for i,f in enumerate(matches): f.text=str(values[i] if i<len(values) else '')

def set_materials_used(rec,value):
 for f in rec.findall('field'):
  name=(f.get('name') or '').lower()
  if 'material' in name and 'used' in name: f.text=str(value or '')

@app.get('/api/export/<int:job_id>')
def export(job_id):
 if not MASTER.exists(): return jsonify(error='Upload a completed reference XML in Settings first'),400
 c=db(); job=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone(); jobs=list(c.execute('SELECT * FROM jobs WHERE day=? ORDER BY position,id',(job['day'],))); st={x['k']:x['v'] for x in c.execute('SELECT * FROM settings')}; c.close()
 materials=request.args.get('materials','').strip()
 if len(materials)>2000: return jsonify(error='Materials text is too long.'),400
 materials_value=f'CEF:\n{materials}' if materials else ''
 i=next(n for n,x in enumerate(jobs) if x['id']==job_id); prev=st.get('leave_home','') if i==0 else jobs[i-1]['finish']; nxt=st.get('return_home','') if i==len(jobs)-1 else jobs[i+1]['start']
 root=ET.parse(MASTER).getroot(); rec=root.find('record'); d=json.loads(job['details']); rec.set('name',f"{job['job_no']} {job['day'].replace('-','/')}")
 long_date=datetime.strptime(job['day'],'%Y-%m-%d').strftime('%d %B %Y')
 resource_text=d.get('A&A Resources') or st.get('resources','Adam Freeman, Peter Bennett, RA25 TLZ'); engineers=assigned_engineers(resource_text)
 mapping={'Front Cover date':long_date,'Front Cover job no.':job['job_no'],'Front Cover client':d.get('Company'),'Booking ID':d.get('Booking ID'),'Job No.':job['job_no'],'Job Number':job['job_no'],'Division':'AM','Date':long_date,'Company':d.get('Company'),'Cust. Ref.':d.get('Cust. Ref.'),'Work Order':d.get('Cust. Ref.'),'Site Address':d.get('Site Address'),'Site Contact':d.get('Site Contact'),'Site Phone':d.get('Site Phone'),'Service':d.get('Service'),'Work Required':d.get('Work Required'),'Depart Time':prev,'Arrive Site':job['start'],'Depart Site':job['finish'],'Arrive Next':nxt,'A&A Resources':resource_text,'A&A Representative':d.get('A&A Representative') or (engineers[0] if engineers else ''),'Customer Representative':'SM','Site Representative':'SM','A&E Hospital location & postcode':nearest_ae(job['postcode'] or postcode(d.get('Site Address',''))),'Lead Engineer':engineers[0] if engineers else '','Engineer 2':engineers[1] if len(engineers)>1 else '','RAMS Number ':st.get('rams','010203'),'Materials Used':materials_value}
 for k,v in mapping.items(): set_occurrences(rec,k,v)
 set_materials_used(rec,materials_value)
 set_occurrence_values(rec,'Customer ',['SM',''])
 set_occurrences(rec,'Further Works Required','0'); set_occurrences(rec,'All Works Complete','0')
 for k in ['Do you have the correct documentation or permit for the task?','Do you understand the task?','Are you authorised & competent to carry out the task?','Are isolations in place?','Do you have the correct PPE and tools for the job?','Are calibrated items in date?','Have all vehicle checks been carried out?']: set_occurrences(rec,k,'Yes')
 set_occurrences(rec,'Are all  electrical equipment PAT test in date?','N/A'); set_occurrences(rec,'Vehicle logged','N/A'); set_occurrences(rec,'Any lessons for next time?','No'); set_occurrences(rec,'Has the work created any new hazards?','No')
 hazard_names=['1. Slips, trips, falls on the same level','2. Falls from height','3. Falling/ flying objects','4. Chemicals/ Harmful substances','5. Heat/ fire/ explosion','6. Asphyxiation, drowning ','7. Risk to plant/ environment ','8. Contact with stationary objects ','9. Manual handling ','10. Stored energy ','11. Vehicle overloaded','12. Excavations ','13. Risk to you from other works','14. Confined space entry ','15. Dust','16. Fumes','17. Noise','18. Vibration','19. Electricity ','20. Asbestos ','21. Contamination/ pollution ','22. Poor lighting ','23. Adverse temperatures ','24. Adverse weather','25. Uncertified equipment ','26. Check risk to others from your work','27. Waterborne diseases (Weils disease)','28. Sharps/ needles/ cuts']
 for n in hazard_names: set_occurrences(rec,n,'1' if n[:2].strip('. ') in {'1','2','3'} or n.startswith('19.') else '0')
 set_occurrence_values(rec,'Hazard numbers',['1','2','3','19','','',''])
 set_occurrence_values(rec,'Has ID',['Maintain a tidy work environment','Maintain equipment','Secure work area with barriers and defensive parking','Isolate and lock off','','',''])
 set_occurrence_values(rec,'Remaining risk1',['Low','Low','Low','Low','','',''])
 buf=io.BytesIO(); ET.ElementTree(root).write(buf,encoding='windows-1252',xml_declaration=True); buf.seek(0)
 return send_file(buf,mimetype='application/xml',as_attachment=True,download_name=f"{job['job_no']}.xml")

@app.delete('/api/jobs/<int:job_id>')
def delete(job_id):
 c=db(); c.execute('DELETE FROM job_materials WHERE job_id=?',(job_id,)); c.execute('DELETE FROM jobs WHERE id=?',(job_id,)); c.commit(); c.close(); return jsonify(ok=True)

from photos import register_photos
from route_planner import register_routes
register_photos(app, db)
register_routes(app, db)

if __name__=='__main__': app.run(host='0.0.0.0',port=1976)
