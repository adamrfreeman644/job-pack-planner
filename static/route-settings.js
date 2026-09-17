(() => {
  const home=document.getElementById('route-home'), key=document.getElementById('route-key');
  const status=document.getElementById('route-status'), save=document.getElementById('route-save'), clear=document.getElementById('route-clear');
  function show(data){home.value=data.home_address||'';key.value='';key.placeholder=data.has_api_key?'Saved — leave blank to keep it':'Paste OpenRouteService API key';status.textContent=data.has_api_key?'OpenRouteService route planning is configured.':'Add a free OpenRouteService API key to enable route planning.';clear.hidden=!data.has_api_key}
  async function api(body){const response=await fetch('/api/route/settings',body===undefined?{cache:'no-store'}:{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not save route settings.');return data}
  save.onclick=async()=>{save.disabled=true;status.textContent='Saving…';try{show(await api({home_address:home.value,api_key:key.value}))}catch(error){status.textContent=error.message}finally{save.disabled=false}};
  clear.onclick=async()=>{clear.disabled=true;try{show(await api({home_address:home.value,clear_api_key:true}))}catch(error){status.textContent=error.message}finally{clear.disabled=false}};
  api().then(show).catch(error=>{status.textContent=error.message});
})();
