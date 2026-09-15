(() => {
  const field = name => document.getElementById('immich-' + name);
  const form = field('form'), status = field('status');
  const controls = Array.from(form.querySelectorAll('button'));
  async function api(path, body) {
    const response = await fetch('/api/photos/' + path, body === undefined ? {cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save photo settings.');
    return data;
  }
  function display(data) {
    for (const name of ['url', 'timezone', 'margin', 'interval']) field(name).value = data[name];
    field('key').value = '';
    field('key').placeholder = data.has_key ? 'Saved — leave blank to keep it' : 'Enter an Immich API key';
    field('key-help').textContent = data.has_key ? 'A key is saved on this server. Changing the address requires a new key.' : 'The key stays on this server and is never displayed again.';
  }
  async function save(test = false, clear = false) {
    if (!clear && !form.reportValidity()) return;
    controls.forEach(button => button.disabled = true);
    status.textContent = test ? 'Saving and checking Immich…' : 'Saving…';
    try {
      const data = await api('settings', {
        url:field('url').value, key:field('key').value, timezone:field('timezone').value,
        margin:Number(field('margin').value), interval:Number(field('interval').value), clear_key:clear,
      });
      display(data);
      status.textContent = test ? (await api('test', {})).message : clear ? 'Saved API key removed.' :
        data.configured ? 'Photo settings saved.' : 'Settings saved. Add an address and API key to connect.';
    } catch (error) { status.textContent = error.message; }
    finally { controls.forEach(button => button.disabled = false); }
  }
  controls.forEach(button => button.disabled = true);
  api('settings').then(data => {
    display(data); status.textContent = data.configured ? 'Immich is configured.' : 'Connect your Immich library to get started.';
    controls.forEach(button => button.disabled = false);
  }).catch(() => { status.textContent = 'Could not load settings. Reload this page to try again.'; });
  form.addEventListener('submit', event => { event.preventDefault(); save(); });
  field('test').addEventListener('click', () => save(true));
  field('disconnect').addEventListener('click', () => save(false, true));
})();
