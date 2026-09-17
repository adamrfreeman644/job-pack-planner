(() => {
 const cardHead=document.querySelector('.card-head'), routeBar=document.createElement('div');
 routeBar.className='route-tools'; routeBar.innerHTML='<button type="button" class="secondary" id="plan-route">Plan route</button><button type="button" class="secondary" id="open-route">Open route</button><button type="button" class="secondary" id="undo-route" hidden>Undo</button>';
 cardHead.insertBefore(routeBar,document.getElementById('save'));
 document.body.insertAdjacentHTML('beforeend',`<section class="route-modal" id="route-modal" role="dialog" aria-modal="true" aria-labelledby="route-title" hidden>
  <div class="route-modal-head"><h2 id="route-title">Daily route</h2><button type="button" id="route-close" aria-label="Close route planner">×</button></div>
  <div class="route-modal-body">
   <div id="route-map" aria-label="Daily route map"></div>
   <fieldset class="route-modes"><legend>Arrange the day</legend><label><input type="radio" name="route-mode" value="least" checked><strong>Least driving</strong><small>Shortest practical round trip</small></label><label><input type="radio" name="route-mode" value="furthest"><strong>Furthest first</strong><small>Start far away and work back towards home</small></label></fieldset>
   <section class="route-stops"><div class="route-section-head"><div><h3>Pickups and drop-offs</h3><p>Add colleague collections or other non-job stops.</p></div><button type="button" id="route-add-stop">+ Add stop</button></div><div id="route-stop-list"></div></section>
   <button type="button" id="route-arrange">Arrange route</button>
   <div id="route-status" role="status"></div><ol id="route-order"></ol>
  </div>
  <div class="route-modal-foot"><button type="button" class="secondary" id="route-cancel">Cancel</button><button type="button" id="route-apply" disabled>Save and apply route</button></div>
 </section>`);
 const planButton=document.getElementById('plan-route'), undoButton=document.getElementById('undo-route'), modal=document.getElementById('route-modal'), stopList=document.getElementById('route-stop-list'), routeOrder=document.getElementById('route-order'), routeStatus=document.getElementById('route-status'), applyButton=document.getElementById('route-apply');
 const locks=new Set(JSON.parse(localStorage.getItem('routeLocks')||'[]')); let priorOrder=null, routeResult=null, draggedId=null, proposal=null, routeMap=null, routeLayer=null;
 const jobsForDay=()=>all.filter(job=>job.day===day.value).sort((a,b)=>a.position-b.position);
 const address=job=>{const details=JSON.parse(job.details||'{}');return details['Site Address']||job.postcode||''};
 const api=async(path,body)=>{const response=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||'Route request failed.');return data};
 function applyOrder(ids){const selected=new Map(all.filter(job=>ids.includes(job.id)).map(job=>[job.id,job])),ordered=ids.map(id=>selected.get(Number(id))).filter(Boolean);ordered.forEach((job,index)=>job.position=index);all=[...all.filter(job=>job.day!==day.value),...ordered];render();enhance()}
 function move(id,delta){const ids=jobsForDay().map(job=>job.id),index=ids.indexOf(Number(id)),next=index+delta;if(index<0||next<0||next>=ids.length)return;priorOrder=[...ids];[ids[index],ids[next]]=[ids[next],ids[index]];undoButton.hidden=false;routeResult=null;applyOrder(ids)}
 function enhance(){
  timeline.querySelectorAll('.event:not(.home)').forEach(event=>{const save=event.querySelector('[data-save]');if(!save)return;const id=Number(save.dataset.save),title=event.querySelector('.event-title');event.dataset.routeId=id;event.draggable=true;event.querySelector('.route-leg')?.remove();
   if(!title.querySelector('.reorder-controls')){const controls=document.createElement('span');controls.className='reorder-controls';controls.innerHTML=`<button type="button" data-move="-1" aria-label="Move job earlier">↑</button><button type="button" data-move="1" aria-label="Move job later">↓</button><button type="button" class="lock-control" data-lock aria-label="${locks.has(id)?'Unlock':'Lock'} job position" aria-pressed="${locks.has(id)}">${locks.has(id)?'Locked':'Unlocked'}</button><span class="drag-handle" title="Drag to reorder">⠿</span>`;title.append(controls)}
   const leg=routeResult?.legs?.find(item=>item.to_key===`job:${id}`);if(leg){const label=document.createElement('div');label.className='route-leg';label.textContent=`${leg.duration_minutes} min · ${leg.distance_miles} miles`;event.querySelector('.event-card').prepend(label)}
  });
  summary.textContent=summary.textContent.replace(/ · route \d+ min \/ [\d.]+ miles$/,'');if(routeResult)summary.textContent+=` · route ${routeResult.duration_minutes} min / ${routeResult.distance_miles} miles`;
 }
 new MutationObserver(()=>{if(!timeline.dataset.enhancing){timeline.dataset.enhancing='1';enhance();delete timeline.dataset.enhancing}}).observe(timeline,{childList:true});
 timeline.addEventListener('click',event=>{const control=event.target.closest('[data-move],[data-lock]');if(!control)return;const id=Number(control.closest('[data-route-id]').dataset.routeId);if(control.hasAttribute('data-move'))move(id,Number(control.dataset.move));else{locks.has(id)?locks.delete(id):locks.add(id);localStorage.setItem('routeLocks',JSON.stringify([...locks]));render()}});
 timeline.addEventListener('dragstart',event=>{const row=event.target.closest('[data-route-id]');if(row){draggedId=Number(row.dataset.routeId);row.classList.add('dragging')}});
 timeline.addEventListener('dragend',event=>{event.target.closest('[data-route-id]')?.classList.remove('dragging');draggedId=null});
 timeline.addEventListener('dragover',event=>{if(event.target.closest('[data-route-id]'))event.preventDefault()});
 timeline.addEventListener('drop',event=>{const target=event.target.closest('[data-route-id]');if(!target||draggedId===null)return;event.preventDefault();const ids=jobsForDay().map(job=>job.id),from=ids.indexOf(draggedId),to=ids.indexOf(Number(target.dataset.routeId));if(from<0||to<0||from===to)return;priorOrder=[...ids];ids.splice(to,0,ids.splice(from,1)[0]);undoButton.hidden=false;routeResult=null;applyOrder(ids)});
 function addStop(stop={}){
  const id=stop.id||((crypto.randomUUID&&crypto.randomUUID())||('stop-'+Date.now()+'-'+Math.random().toString(16).slice(2))),row=document.createElement('div');row.className='route-stop-row';row.dataset.stopId=id;
  row.innerHTML=`<select aria-label="Stop type"><option value="pickup">Pickup</option><option value="dropoff">Drop-off</option></select><input class="stop-label" placeholder="Person or collection name" aria-label="Person or collection name"><input class="stop-address" placeholder="Postcode or address" aria-label="Pickup or drop-off address"><button type="button" class="stop-remove" aria-label="Remove stop">×</button>`;
  row.querySelector('select').value=stop.type||'pickup';row.querySelector('.stop-label').value=stop.label||'';row.querySelector('.stop-address').value=stop.address||'';row.querySelector('.stop-remove').onclick=()=>row.remove();stopList.append(row);
 }
 function stops(){return [...stopList.querySelectorAll('.route-stop-row')].map(row=>({id:row.dataset.stopId,type:row.querySelector('select').value,label:row.querySelector('.stop-label').value.trim(),address:row.querySelector('.stop-address').value.trim()})).filter(stop=>stop.label||stop.address)}
 function drawMap(result){
  if(!window.L||!result.geometry?.length){document.getElementById('route-map').textContent='Map preview unavailable. The stop order is still shown below.';return}
  if(!routeMap){routeMap=L.map('route-map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(routeMap)}
  if(routeLayer)routeLayer.remove();const latlngs=result.geometry.map(point=>[point[1],point[0]]);routeLayer=L.polyline(latlngs,{color:'#087f6d',weight:5}).addTo(routeMap);routeMap.fitBounds(routeLayer.getBounds(),{padding:[24,24]});setTimeout(()=>routeMap.invalidateSize(),50);
 }
 function showProposal(result){
  routeOrder.innerHTML=result.items.map((item,index)=>{const leg=(result.legs||[]).find(value=>value.to_key===item.key);return `<li><span class="route-number">${index+1}</span><div><strong>${esc(item.type==='pickup'?'Pickup · '+item.label:item.type==='dropoff'?'Drop-off · '+item.label:item.label)}</strong><small>${esc(item.address)}</small>${leg?`<em>${leg.duration_minutes} min · ${leg.distance_miles} miles from previous stop</em>`:''}</div></li>`}).join('');
  routeStatus.textContent=`${result.distance_miles} miles · about ${result.duration_minutes} minutes driving`;drawMap(result);applyButton.disabled=false;
 }
 async function openPlanner(){
  const jobs=jobsForDay();if(!jobs.length){pop('No jobs to plan for this date.');return}proposal=null;applyButton.disabled=true;routeOrder.innerHTML='';routeStatus.textContent='Choose how to arrange the route.';stopList.innerHTML='';modal.hidden=false;document.body.style.overflow='hidden';
  try{const saved=await api('/api/route/day/'+day.value);(saved.stops||[]).forEach(addStop);if(saved.items?.length){proposal=saved;showProposal(saved)}}catch(error){routeStatus.textContent=error.message}
  setTimeout(()=>routeMap?.invalidateSize(),100);
 }
 function closePlanner(){modal.hidden=true;document.body.style.overflow='';planButton.focus()}
 document.getElementById('route-add-stop').onclick=()=>addStop();document.getElementById('route-close').onclick=closePlanner;document.getElementById('route-cancel').onclick=closePlanner;planButton.onclick=openPlanner;
 document.getElementById('route-arrange').onclick=async event=>{const button=event.currentTarget,mode=document.querySelector('[name="route-mode"]:checked').value;button.disabled=true;button.textContent='Arranging…';routeStatus.textContent='Checking addresses and calculating the route…';applyButton.disabled=true;
  try{proposal=await api('/api/route/plan',{day:day.value,job_ids:jobsForDay().map(job=>job.id),locked_ids:[...locks],stops:stops(),mode});showProposal(proposal)}catch(error){routeStatus.textContent=error.message}finally{button.disabled=false;button.textContent='Arrange route'}
 };
 applyButton.onclick=async()=>{if(!proposal)return;applyButton.disabled=true;applyButton.textContent='Saving…';try{const result=await api('/api/route/apply',proposal);priorOrder=jobsForDay().map(job=>job.id);routeResult=proposal;applyOrder(result.ordered_ids);undoButton.hidden=false;closePlanner();pop('Route saved and applied')}catch(error){routeStatus.textContent=error.message;applyButton.disabled=false}finally{applyButton.textContent='Save and apply route'}};
 async function googleRoute(){let saved;try{saved=await api('/api/route/day/'+day.value)}catch(_){saved=null}const items=saved?.items?.length?saved.items:jobsForDay().map(job=>({address:address(job)})),points=items.map(item=>item.address).filter(Boolean),home=settings.home_address||'';if(!points.length){pop('No route is available for this day.');return}const origin=home||points[0],destination=home||points.at(-1),waypoints=home?points:points.slice(1,-1),params=new URLSearchParams({api:'1',origin,destination,travelmode:'driving'});if(waypoints.length)params.set('waypoints',waypoints.join('|'));window.open('https://www.google.com/maps/dir/?'+params,'_blank','noopener')}
 document.getElementById('open-route').onclick=googleRoute;undoButton.onclick=()=>{if(priorOrder){const restore=priorOrder;priorOrder=null;routeResult=null;undoButton.hidden=true;applyOrder(restore);pop('Previous order restored')}};document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!modal.hidden)closePlanner()});
 day.addEventListener('change',()=>{priorOrder=null;routeResult=null;undoButton.hidden=true;setTimeout(enhance)});window.addEventListener('load',async()=>{try{const value=await api('/api/route/settings');settings.home_address=value.home_address||''}catch(_){}enhance()});
})();
