(() => {
 const cardHead=document.querySelector('.card-head'), routeBar=document.createElement('div');
 routeBar.className='route-tools'; routeBar.innerHTML='<button type="button" class="secondary route-icon" id="plan-route" aria-label="Plan day" title="Plan day"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4 15 6l6-2v16l-6 2-6-2-6 2V6l6-2Zm0 2.2v11.6m6-9.6v11.6"/></svg></button><button type="button" class="secondary route-icon google-route-icon" id="open-route" aria-label="Open route in Google Maps" title="Open route in Google Maps"><svg viewBox="0 0 24 24" aria-hidden="true"><path class="g-blue" d="M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7Z"/><path class="g-red" d="M12 2v20s7-7.75 7-13a7 7 0 0 0-7-7Z"/><circle cx="12" cy="9" r="2.7" fill="#fff"/><path class="g-yellow" d="M5.4 14.2 12 22v-7.8Z"/><path class="g-green" d="M18.6 14.2 12 22v-7.8Z"/></svg></button>';
 cardHead.insertBefore(routeBar,document.getElementById('save'));
 document.body.insertAdjacentHTML('beforeend',`<section class="route-modal" id="route-modal" role="dialog" aria-modal="true" aria-labelledby="route-title" hidden>
  <div class="route-modal-head"><h2 id="route-title">Daily route</h2><button type="button" id="route-fullscreen" aria-label="Show map full screen" title="Show map full screen">⛶</button><button type="button" id="route-close" aria-label="Close route planner">×</button></div>
  <div class="route-modal-body">
   <div id="route-map" aria-label="Daily route map"></div>
   <fieldset class="route-modes"><legend>How should the jobs be arranged?</legend><label><input type="radio" name="route-mode" value="least" checked><strong>Auto</strong><small>Choose the route with the least driving</small></label><label><input type="radio" name="route-mode" value="furthest"><strong>Semi-auto</strong><small>Start with the furthest job and work back home</small></label><label><input type="radio" name="route-mode" value="manual"><strong>Manual</strong><small>Put the jobs in your preferred order</small></label></fieldset>
   <section class="manual-route-order" id="manual-route-order" hidden><h3>Manual job order</h3><p>Pickups stay before these jobs and drop-offs stay afterwards.</p><ol id="manual-job-list"></ol></section>
   <section class="route-stops"><div class="route-section-head"><div><h3>Colleague collections</h3><p>Each colleague is picked up before the jobs and dropped home afterwards.</p></div><button type="button" id="route-add-stop">+ Add colleague</button></div><div id="route-stop-list"></div></section>
   <button type="button" id="route-arrange">Arrange route</button>
   <div id="route-status" role="status"></div><ol id="route-order"></ol>
  </div>
  <div class="route-modal-foot"><button type="button" class="secondary" id="route-cancel">Cancel</button><button type="button" id="route-apply" disabled>Save and apply route</button></div>
 </section>`);
 const planButton=document.getElementById('plan-route'), fullscreenButton=document.getElementById('route-fullscreen'), modal=document.getElementById('route-modal'), stopList=document.getElementById('route-stop-list'), routeOrder=document.getElementById('route-order'), routeStatus=document.getElementById('route-status'), applyButton=document.getElementById('route-apply'), manualPanel=document.getElementById('manual-route-order'), manualList=document.getElementById('manual-job-list');
 const locks=new Set(JSON.parse(localStorage.getItem('routeLocks')||'[]')); let priorOrder=null, routeResult=null, draggedId=null, proposal=null, routeMap=null, routeLayer=null, routeMarkers=null;
 const jobsForDay=()=>all.filter(job=>job.day===day.value).sort((a,b)=>a.position-b.position);
 let swipeStart=null;
 function changeDayBy(days){const value=new Date(day.value+'T12:00:00');value.setDate(value.getDate()+days);day.value=value.toISOString().slice(0,10);day.dispatchEvent(new Event('change'))}
 timeline.addEventListener('pointerdown',event=>{if(event.pointerType==='touch')swipeStart={x:event.clientX,y:event.clientY}});
 timeline.addEventListener('pointerup',event=>{if(!swipeStart||event.pointerType!=='touch')return;const dx=event.clientX-swipeStart.x,dy=event.clientY-swipeStart.y;swipeStart=null;if(Math.abs(dx)<70||Math.abs(dx)<=Math.abs(dy))return;changeDayBy(dx<0?1:-1)});
 timeline.addEventListener('pointercancel',()=>{swipeStart=null});
 const address=job=>{const details=JSON.parse(job.details||'{}');return details['Site Address']||job.postcode||''};
 const api=async(path,body)=>{const response=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||'Route request failed.');return data};
 function applyOrder(ids){const selected=new Map(all.filter(job=>ids.includes(job.id)).map(job=>[job.id,job])),ordered=ids.map(id=>selected.get(Number(id))).filter(Boolean);ordered.forEach((job,index)=>job.position=index);all=[...all.filter(job=>job.day!==day.value),...ordered];render();enhance()}
 function enhance(){
  timeline.querySelectorAll('.event:not(.home)').forEach(event=>{const save=event.querySelector('[data-save]');if(!save)return;const id=Number(save.dataset.save);event.dataset.routeId=id;event.draggable=false;event.querySelector('.route-leg')?.remove();
   const leg=routeResult?.legs?.find(item=>item.to_key===`job:${id}`);if(leg){const label=document.createElement('div');label.className='route-leg';label.textContent=`${leg.duration_minutes} min · ${leg.distance_miles} miles`;event.querySelector('.event-card').prepend(label)}
  });
  summary.textContent=summary.textContent.replace(/ · route \d+ min \/ [\d.]+ miles$/,'');if(routeResult)summary.textContent+=` · route ${routeResult.duration_minutes} min / ${routeResult.distance_miles} miles`;
 }
 new MutationObserver(()=>{if(!timeline.dataset.enhancing){timeline.dataset.enhancing='1';enhance();delete timeline.dataset.enhancing}}).observe(timeline,{childList:true});
timeline.addEventListener('dragstart',event=>{const row=event.target.closest('[data-route-id]');if(row){draggedId=Number(row.dataset.routeId);row.classList.add('dragging')}});
 timeline.addEventListener('dragend',event=>{event.target.closest('[data-route-id]')?.classList.remove('dragging');draggedId=null});
 timeline.addEventListener('dragover',event=>{if(event.target.closest('[data-route-id]'))event.preventDefault()});
 timeline.addEventListener('drop',event=>{const target=event.target.closest('[data-route-id]');if(!target||draggedId===null)return;event.preventDefault();const ids=jobsForDay().map(job=>job.id),from=ids.indexOf(draggedId),to=ids.indexOf(Number(target.dataset.routeId));if(from<0||to<0||from===to)return;ids.splice(to,0,ids.splice(from,1)[0]);routeResult=null;applyOrder(ids)});
 timeline.addEventListener('change',event=>{if(!event.target.matches('[data-key="start"],[data-key="finish"]'))return;setTimeout(()=>{const ids=jobsForDay().slice().sort((a,b)=>a.start.localeCompare(b.start)||a.finish.localeCompare(b.finish)||a.position-b.position).map(job=>job.id);if(ids.some((id,index)=>id!==jobsForDay()[index].id))applyOrder(ids)},0)});
 function addStop(stop={}){
  const id=stop.id||((crypto.randomUUID&&crypto.randomUUID())||('stop-'+Date.now()+'-'+Math.random().toString(16).slice(2))),row=document.createElement('div');row.className='route-stop-row';row.dataset.stopId=id;
  row.innerHTML=`<span class="collection-pair">Pickup + drop-off</span><input class="stop-label" placeholder="Colleague name" aria-label="Colleague name"><input class="stop-address" placeholder="Home postcode or address" aria-label="Colleague home address"><button type="button" class="stop-remove" aria-label="Remove colleague">×</button>`;
  row.querySelector('.stop-label').value=stop.label||'';row.querySelector('.stop-address').value=stop.address||'';row.querySelector('.stop-remove').onclick=()=>row.remove();stopList.append(row);
 }
 function stops(){return [...stopList.querySelectorAll('.route-stop-row')].map(row=>({id:row.dataset.stopId,type:'collection',label:row.querySelector('.stop-label').value.trim(),address:row.querySelector('.stop-address').value.trim()})).filter(stop=>stop.label||stop.address)}
 function renderManual(ids=jobsForDay().map(job=>job.id)){const jobs=new Map(jobsForDay().map(job=>[job.id,job]));manualList.innerHTML=ids.map((id,index)=>{const job=jobs.get(Number(id));return `<li data-manual-id="${id}"><span class="route-number">${index+1}</span><strong>${esc(job?.job_no||id)} · ${esc(job?.title||'Job')}</strong><span class="manual-buttons"><button type="button" data-manual-move="-1" aria-label="Move job earlier">↑</button><button type="button" data-manual-move="1" aria-label="Move job later">↓</button></span></li>`}).join('')}
 function manualIds(){return [...manualList.querySelectorAll('[data-manual-id]')].map(row=>Number(row.dataset.manualId))}
 function drawMap(result){
  if(!window.L||!result.geometry?.length){document.getElementById('route-map').textContent='Map preview unavailable. The stop order is still shown below.';return}
  if(!routeMap){routeMap=L.map('route-map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(routeMap)}
  if(routeLayer)routeLayer.remove();if(routeMarkers)routeMarkers.remove();const latlngs=result.geometry.map(point=>[point[1],point[0]]);routeLayer=L.polyline(latlngs,{color:'#087f6d',weight:5}).addTo(routeMap);routeMarkers=L.layerGroup().addTo(routeMap);
  const stops=[{label:'Home',coordinates:result.home_coordinates}].concat(result.items||[]);
  let jobNumber=0;stops.forEach((stop,index)=>{const coords=stop.coordinates;if(!Array.isArray(coords)||coords.length<2)return;const label=stop.label||'Home',isMeeting=stop.type==='pickup'||stop.type==='dropoff',markerLabel=index===0?'H':isMeeting?'M':++jobNumber;const marker=L.marker([coords[1],coords[0]],{icon:L.divIcon({className:'route-pin-wrap',html:`<span class="route-pin"><span>${markerLabel}</span></span>`,iconSize:[30,30],iconAnchor:[15,15]})}).bindPopup(`<strong>${index===0?'Home':isMeeting?'Meeting · '+esc(label):jobNumber+'. '+esc(label)}</strong><br>${esc(stop.address||'')}`);marker.addTo(routeMarkers)});
  routeMap.fitBounds(routeLayer.getBounds(),{padding:[24,24]});setTimeout(()=>routeMap.invalidateSize(),50);
 }
 function showProposal(result){
  routeOrder.innerHTML=result.items.map((item,index)=>{const leg=(result.legs||[]).find(value=>value.to_key===item.key);return `<li><span class="route-number">${index+1}</span><div><strong>${esc(item.type==='pickup'?'Pickup · '+item.label:item.type==='dropoff'?'Drop-off · '+item.label:item.label)}</strong><small>${esc(item.address)}</small>${leg?`<em>${leg.duration_minutes} min · ${leg.distance_miles} miles from previous stop</em>`:''}</div></li>`}).join('');
  routeStatus.textContent=`${result.distance_miles} miles · about ${result.duration_minutes} minutes driving`;drawMap(result);applyButton.disabled=false;
 }
 async function openPlanner(){
  const jobs=jobsForDay();if(!jobs.length){pop('No jobs to plan for this date.');return}proposal=null;applyButton.disabled=true;routeOrder.innerHTML='';routeStatus.textContent='Choose how to arrange the route.';stopList.innerHTML='';renderManual();manualPanel.hidden=true;document.querySelector('[name="route-mode"][value="least"]').checked=true;modal.hidden=false;document.body.style.overflow='hidden';
  try{const saved=await api('/api/route/day/'+day.value);(saved.stops||[]).forEach(addStop);if(saved.items?.length){proposal=saved;showProposal(saved)}}catch(error){routeStatus.textContent=error.message}
  setTimeout(()=>routeMap?.invalidateSize(),100);
 }
 function toggleMapFullscreen(force){const map=document.getElementById('route-map'),open=force===undefined?!map.classList.contains('map-fullscreen'):force;map.classList.toggle('map-fullscreen',open);fullscreenButton.setAttribute('aria-label',open?'Exit full screen map':'Show map full screen');fullscreenButton.title=open?'Exit full screen map':'Show map full screen';setTimeout(()=>routeMap?.invalidateSize(),50)}
 function closePlanner(){toggleMapFullscreen(false);modal.hidden=true;document.body.style.overflow='';planButton.focus()}
 document.getElementById('route-add-stop').onclick=()=>addStop();fullscreenButton.onclick=()=>toggleMapFullscreen();document.getElementById('route-close').onclick=closePlanner;document.getElementById('route-cancel').onclick=closePlanner;planButton.onclick=openPlanner;
 document.querySelectorAll('[name="route-mode"]').forEach(input=>input.onchange=()=>{manualPanel.hidden=input.value!=='manual'||!input.checked;if(input.value==='manual'&&input.checked)renderManual(manualIds().length?manualIds():undefined)});
 manualList.addEventListener('click',event=>{const button=event.target.closest('[data-manual-move]');if(!button)return;const row=button.closest('[data-manual-id]'),ids=manualIds(),from=ids.indexOf(Number(row.dataset.manualId)),to=from+Number(button.dataset.manualMove);if(to<0||to>=ids.length)return;[ids[from],ids[to]]=[ids[to],ids[from]];renderManual(ids)});
 document.getElementById('route-arrange').onclick=async event=>{const button=event.currentTarget,mode=document.querySelector('[name="route-mode"]:checked').value;button.disabled=true;button.textContent='Arranging…';routeStatus.textContent='Checking addresses and calculating the route…';applyButton.disabled=true;
  try{proposal=await api('/api/route/plan',{day:day.value,job_ids:mode==='manual'?manualIds():jobsForDay().map(job=>job.id),locked_ids:[],stops:stops(),mode});showProposal(proposal)}catch(error){routeStatus.textContent=error.message}finally{button.disabled=false;button.textContent='Arrange route'}
 };
 applyButton.onclick=async()=>{if(!proposal)return;applyButton.disabled=true;applyButton.textContent='Saving…';try{const result=await api('/api/route/apply',proposal);routeResult=proposal;applyOrder(result.ordered_ids);closePlanner();pop('Route saved and applied')}catch(error){routeStatus.textContent=error.message;applyButton.disabled=false}finally{applyButton.textContent='Save and apply route'}};
 async function googleRoute(){let saved;try{saved=await api('/api/route/day/'+day.value)}catch(_){saved=null}const items=saved?.items?.length?saved.items:jobsForDay().map(job=>({address:address(job)})),points=items.map(item=>item.address).filter(Boolean),home=settings.home_address||'';if(!points.length){pop('No route is available for this day.');return}const origin=home||points[0],destination=home||points.at(-1),waypoints=home?points:points.slice(1,-1),params=new URLSearchParams({api:'1',origin,destination,travelmode:'driving'});if(waypoints.length)params.set('waypoints',waypoints.join('|'));window.open('https://www.google.com/maps/dir/?'+params,'_blank','noopener')}
 document.getElementById('open-route').onclick=googleRoute;document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;const map=document.getElementById('route-map');if(map.classList.contains('map-fullscreen'))toggleMapFullscreen(false);else if(!modal.hidden)closePlanner()});
 day.addEventListener('change',()=>{routeResult=null;setTimeout(enhance)});window.addEventListener('load',async()=>{try{const value=await api('/api/route/settings');settings.home_address=value.home_address||''}catch(_){}enhance()});
})();
