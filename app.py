from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from pathlib import Path
from datetime import datetime
import sqlite3, xml.etree.ElementTree as ET, io, re, json, os

app=Flask(__name__)
DATA=Path('/data'); DATA.mkdir(exist_ok=True)
DB=DATA/'planner.db'; MASTER=DATA/'master.xml'
SHARE=Path(os.getenv('JOB_PACK_SHARE','/imports'))

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

def import_booking(raw):
 root=ET.fromstring(raw); rec=root.find('record')
 if rec is None: return None
 d=fields(rec); j=first(d,'Job No.','Job Number'); date=first(d,'Date')
 if not j: return None
 try: day=datetime.strptime(date,'%d-%m-%Y').date().isoformat()
 except: day=datetime.now().date().isoformat()
 addr=first(d,'Site Address'); company=first(d,'Company'); work=first(d,'Work Required'); title=(addr.splitlines()[0] if addr else company) or j
 details=json.dumps({k:first(d,k) for k in ['Booking ID','Job No.','Division','Date','Company','Cust. Ref.','Site Address','Site Contact','Site Phone','Service','Work Required','A&A Resources','A&A Representative']})
 c=db(); existing=c.execute('SELECT id FROM jobs WHERE job_no=?',(j,)).fetchone()
 if existing:
  c.execute('UPDATE jobs SET day=?,booking_xml=?,title=?,postcode=?,details=? WHERE job_no=?',(day,raw.decode('utf-8','replace'),title,postcode(addr),details,j))
 else:
  pos=c.execute('SELECT COALESCE(MAX(position),0)+1 FROM jobs WHERE day=?',(day,)).fetchone()[0]
  c.execute('INSERT INTO jobs(job_no,day,booking_xml,title,postcode,start,finish,position,details) VALUES(?,?,?,?,?,?,?,?,?)',(j,day,raw.decode('utf-8','replace'),title,postcode(addr),'09:00','10:00',pos,details))
 c.commit(); c.close(); return j

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
    job=import_booking(raw)
    if job: added.append(job)
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

@app.post('/api/save')
def save():
 body=request.json; c=db()
 for i,j in enumerate(body['jobs']): c.execute('UPDATE jobs SET day=?,start=?,finish=?,position=? WHERE id=?',(body['day'],j['start'],j['finish'],i,j['id']))
 for k,v in body.get('settings',{}).items(): c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)',(k,str(v)))
 c.commit(); c.close(); return jsonify(ok=True)

def set_occurrences(rec,name,value):
 for f in rec.findall('field'):
  if f.get('name')==name: f.text=str(value or '')

def set_occurrence_values(rec,name,values):
 matches=[f for f in rec.findall('field') if f.get('name')==name]
 for i,f in enumerate(matches): f.text=str(values[i] if i<len(values) else '')

@app.get('/api/export/<int:job_id>')
def export(job_id):
 if not MASTER.exists(): return jsonify(error='Upload a completed reference XML in Settings first'),400
 c=db(); job=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone(); jobs=list(c.execute('SELECT * FROM jobs WHERE day=? ORDER BY position,id',(job['day'],))); st={x['k']:x['v'] for x in c.execute('SELECT * FROM settings')}; c.close()
 i=next(n for n,x in enumerate(jobs) if x['id']==job_id); prev=st.get('leave_home','') if i==0 else jobs[i-1]['finish']; nxt=st.get('return_home','') if i==len(jobs)-1 else jobs[i+1]['start']
 root=ET.parse(MASTER).getroot(); rec=root.find('record'); d=json.loads(job['details']); rec.set('name',f"{job['job_no']} {job['day'].replace('-','/')}")
 long_date=datetime.strptime(job['day'],'%Y-%m-%d').strftime('%d %B %Y')
 resource_text=d.get('A&A Resources') or st.get('resources','Adam Freeman, Peter Bennett, RA25 TLZ'); engineers=assigned_engineers(resource_text)
 mapping={'Front Cover date':long_date,'Front Cover job no.':job['job_no'],'Front Cover client':d.get('Company'),'Booking ID':d.get('Booking ID'),'Job No.':job['job_no'],'Job Number':job['job_no'],'Division':'AM','Date':long_date,'Company':d.get('Company'),'Cust. Ref.':d.get('Cust. Ref.'),'Work Order':d.get('Cust. Ref.'),'Site Address':d.get('Site Address'),'Site Contact':d.get('Site Contact'),'Site Phone':d.get('Site Phone'),'Service':d.get('Service'),'Work Required':d.get('Work Required'),'Depart Time':prev,'Arrive Site':job['start'],'Depart Site':job['finish'],'Arrive Next':nxt,'A&A Resources':resource_text,'A&A Representative':d.get('A&A Representative') or (engineers[0] if engineers else ''),'Lead Engineer':engineers[0] if engineers else '','Engineer 2':engineers[1] if len(engineers)>1 else '','RAMS Number ':st.get('rams','010203')}
 for k,v in mapping.items(): set_occurrences(rec,k,v)
 set_occurrences(rec,'Further Works Required','0'); set_occurrences(rec,'All Works Complete','0')
 for k in ['Do you have the correct documentation or permit for the task?','Do you understand the task?','Are you authorised & competent to carry out the task?','Are isolations in place?','Do you have the correct PPE and tools for the job?','Are calibrated items in date?','Have all vehicle checks been carried out?']: set_occurrences(rec,k,'Yes')
 set_occurrences(rec,'Are all  electrical equipment PAT test in date?','N/A'); set_occurrences(rec,'Vehicle logged','N/A'); set_occurrences(rec,'Any lessons for next time?','No'); set_occurrences(rec,'Has the work created any new hazards?','No')
 hazard_names=['1. Slips, trips, falls on the same level','2. Falls from height','3. Falling/ flying objects','4. Chemicals/ Harmful substances','5. Heat/ fire/ explosion','6. Asphyxiation, drowning ','7. Risk to plant/ environment ','8. Contact with stationary objects ','9. Manual handling ','10. Stored energy ','11. Vehicle overloaded','12. Excavations ','13. Risk to you from other works','14. Confined space entry ','15. Dust','16. Fumes','17. Noise','18. Vibration','19. Electricity ','20. Asbestos ','21. Contamination/ pollution ','22. Poor lighting ','23. Adverse temperatures ','24. Adverse weather','25. Uncertified equipment ','26. Check risk to others from your work','27. Waterborne diseases (Weils disease)','28. Sharps/ needles/ cuts']
 for n in hazard_names: set_occurrences(rec,n,'1' if n[:2].strip('. ') in {'1','2','3'} or n.startswith('19.') else '0')
 set_occurrence_values(rec,'Hazard numbers',['1','2','3','19','','',''])
 set_occurrence_values(rec,'Has ID',['Maintain a tidy work environment','Maintain equipment','Secure work area with barriers and defensive parking','Isolate and lock off','','',''])
 set_occurrence_values(rec,'Remaining risk1',['Low','Low','Low','Low','','',''])
 buf=io.BytesIO(); ET.ElementTree(root).write(buf,encoding='windows-1252',xml_declaration=True); buf.seek(0)
 return send_file(buf,mimetype='text/xml',as_attachment=True,download_name=f"{job['job_no']}-prepared.xml")

@app.delete('/api/jobs/<int:job_id>')
def delete(job_id):
 c=db(); c.execute('DELETE FROM jobs WHERE id=?',(job_id,)); c.commit(); c.close(); return jsonify(ok=True)

if __name__=='__main__': app.run(host='0.0.0.0',port=1976)
