(() => {
  const cardHead = document.querySelector('.card-head');
  const routeBar = document.createElement('div');
  routeBar.className = 'route-tools';
  routeBar.innerHTML = '<button type="button" class="secondary" id="plan-route">Plan route</button><button type="button" class="secondary" id="open-route">Open route</button><button type="button" class="secondary" id="undo-route" hidden>Undo</button>';
  cardHead.insertBefore(routeBar, document.getElementById('save'));
  const planButton = document.getElementById('plan-route');
  const undoButton = document.getElementById('undo-route');
  const locks = new Set(JSON.parse(localStorage.getItem('routeLocks') || '[]'));
  let priorOrder = null, routeResult = null, draggedId = null;

  const jobsForDay = () => all.filter(job => job.day === day.value).sort((a,b) => a.position-b.position);
  const storeLocks = () => localStorage.setItem('routeLocks', JSON.stringify([...locks]));
  function applyOrder(ids) {
    const rank = new Map(ids.map((id,index) => [Number(id),index]));
    all.filter(job => rank.has(job.id)).forEach(job => { job.position = rank.get(job.id); });
    render(); enhance();
  }
  function move(id, delta) {
    const ids = jobsForDay().map(job => job.id), index = ids.indexOf(Number(id));
    const next = index + delta;
    if (index < 0 || next < 0 || next >= ids.length) return;
    priorOrder = [...ids]; [ids[index], ids[next]] = [ids[next], ids[index]];
    undoButton.hidden = false; routeResult = null; applyOrder(ids);
  }
  function address(job) {
    const details = JSON.parse(job.details || '{}');
    return details['Site Address'] || job.postcode || '';
  }
  function mapsUrl() {
    const jobs = jobsForDay(), home = settings.home_address || '';
    if (!jobs.length) return '';
    const points = jobs.map(address).filter(Boolean);
    const origin = home || points[0], destination = home || points.at(-1);
    const waypoints = home ? points : points.slice(1,-1);
    const params = new URLSearchParams({api:'1',origin,destination,travelmode:'driving'});
    if (waypoints.length) params.set('waypoints',waypoints.join('|'));
    return 'https://www.google.com/maps/dir/?' + params;
  }
  function enhance() {
    const jobs = jobsForDay();
    timeline.querySelectorAll('.event:not(.home)').forEach(event => {
      const save = event.querySelector('[data-save]'); if (!save) return;
      const id = Number(save.dataset.save), title = event.querySelector('.event-title');
      event.dataset.routeId = id; event.draggable = true;
      if (!title.querySelector('.reorder-controls')) {
        const controls = document.createElement('span'); controls.className = 'reorder-controls';
        controls.innerHTML = `<button type="button" data-move="-1" aria-label="Move job earlier">↑</button><button type="button" data-move="1" aria-label="Move job later">↓</button><button type="button" data-lock aria-label="Lock job position" aria-pressed="${locks.has(id)}">${locks.has(id)?'🔒':'🔓'}</button><span class="drag-handle" title="Drag to reorder">⠿</span>`;
        title.append(controls);
      }
      const leg = routeResult?.legs?.find(item => item.to_id === id);
      if (leg) {
        const label = document.createElement('div'); label.className = 'route-leg' + (leg.warning?' warning':'');
        label.textContent = `${leg.duration_minutes} min · ${leg.distance_miles} miles${leg.warning?' · '+leg.warning:''}`;
        event.querySelector('.event-card').prepend(label);
      }
    });
    if (routeResult) summary.textContent += ` · route ${routeResult.duration_minutes} min / ${routeResult.distance_miles} miles`;
  }
  new MutationObserver(() => { if (!timeline.dataset.enhancing) { timeline.dataset.enhancing='1'; enhance(); delete timeline.dataset.enhancing; } }).observe(timeline,{childList:true});
  timeline.addEventListener('click', event => {
    const control = event.target.closest('[data-move],[data-lock]'); if (!control) return;
    const id = Number(control.closest('[data-route-id]').dataset.routeId);
    if (control.hasAttribute('data-move')) move(id, Number(control.dataset.move));
    else { locks.has(id)?locks.delete(id):locks.add(id); storeLocks(); enhance(); render(); }
  });
  timeline.addEventListener('dragstart', event => { const row=event.target.closest('[data-route-id]'); if(row){draggedId=Number(row.dataset.routeId);row.classList.add('dragging');} });
  timeline.addEventListener('dragend', event => { event.target.closest('[data-route-id]')?.classList.remove('dragging'); draggedId=null; });
  timeline.addEventListener('dragover', event => { if (event.target.closest('[data-route-id]')) event.preventDefault(); });
  timeline.addEventListener('drop', event => {
    const target=event.target.closest('[data-route-id]'); if(!target||draggedId===null)return; event.preventDefault();
    const ids=jobsForDay().map(job=>job.id), from=ids.indexOf(draggedId), to=ids.indexOf(Number(target.dataset.routeId));
    if(from<0||to<0||from===to)return; priorOrder=[...ids]; ids.splice(to,0,ids.splice(from,1)[0]); undoButton.hidden=false; routeResult=null; applyOrder(ids);
  });
  planButton.onclick = async () => {
    const jobs=jobsForDay(); if(!jobs.length){pop('No jobs to plan for this date.');return;}
    priorOrder=jobs.map(job=>job.id); planButton.disabled=true; planButton.textContent='Planning…';
    try {
      const response=await fetch('/api/route/plan',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({job_ids:priorOrder,locked_ids:[...locks],leave_home:document.getElementById('leave').value})});
      const data=await response.json(); if(!response.ok)throw new Error(data.error||'Route planning failed.');
      routeResult=data; undoButton.hidden=false; applyOrder(data.ordered_ids); pop('Best route applied · press Save day to keep it');
    } catch(error) { pop(error.message); }
    finally { planButton.disabled=false; planButton.textContent='Plan route'; }
  };
  document.getElementById('open-route').onclick=()=>{const url=mapsUrl();if(url)window.open(url,'_blank','noopener');else pop('No route is available for this day.')};
  undoButton.onclick=()=>{if(priorOrder){const restore=priorOrder;priorOrder=null;routeResult=null;undoButton.hidden=true;applyOrder(restore);pop('Previous order restored')}};
  day.addEventListener('change',()=>{priorOrder=null;routeResult=null;undoButton.hidden=true;setTimeout(enhance)});
  window.addEventListener('load',async()=>{try{const routeSettings=await fetch('/api/route/settings',{cache:'no-store'}).then(r=>r.json());settings.home_address=routeSettings.home_address||'';}catch(_){ } enhance();});
})();
