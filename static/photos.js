(() => {
  const viewer = document.getElementById('photo-viewer');
  const picture = document.getElementById('photo-picture');
  const message = document.getElementById('photo-message');
  const checkButton = document.getElementById('check-photos');
  const previous = viewer.querySelector('.previous');
  const next = viewer.querySelector('.next');
  let config = null, checking = false, lastCheck = 0, sequence = [], index = 0;
  let open = false, generation = 0, actualFullscreen = false, originButton = null;
  const counts = new Map();
  const key = job => `${job.day}:${job.start}:${job.finish}`;

  async function api(url, body) {
    const response = await fetch(url, body === undefined ? {cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
    });
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('The planner could not complete the photo check.'); }
    if (!response.ok) throw new Error(data.error || 'Photo check failed.');
    return data;
  }

  function paintCounts() {
    document.querySelectorAll('[data-photos]').forEach(button => {
      const job = all.find(j => j.id === Number(button.dataset.photos));
      const cached = counts.get(job?.id);
      button.textContent = cached && cached.key === key(job) ? `Photos (${cached.count})` : 'Photos';
    });
  }
  new MutationObserver(paintCounts).observe(timeline, {childList:true});

  async function checkJob(job) {
    const savedKey = key(job);
    const result = await api(`/api/jobs/${job.id}/photos/check`, {});
    counts.set(job.id, {key:savedKey, count:result.count});
    paintCounts();
    return result;
  }

  async function checkDay(manual = false) {
    if (checking || open || (!manual && document.hidden)) return;
    checking = true;
    checkButton.disabled = true;
    checkButton.textContent = 'Checking…';
    try {
      config = await api('/api/photos/settings');
      if (!config.configured) {
        if (manual) pop('Connect Immich in Settings first.');
        return;
      }
      const selectedDay = day.value;
      const jobs = all.filter(j => j.day === selectedDay);
      if (!jobs.length) { if (manual) pop('No jobs to check for this date.'); return; }
      const saved = (await api('/api/state')).jobs;
      let total = 0, firstError = '';
      for (const job of jobs) {
        if (open || day.value !== selectedDay || (!manual && document.hidden)) break;
        const stored = saved.find(j => j.id === job.id);
        if (!stored || key(stored) !== key(job)) {
          firstError ||= 'Save day before checking photos for edited times.';
          continue;
        }
        try { total += (await checkJob(job)).count; }
        catch (error) { firstError ||= error.message; }
      }
      checkButton.title = firstError;
      if (manual && !open) pop(firstError || `Photo check complete · ${total} matches`);
    } catch (error) {
      // Quiet background checks still leave a useful status on the manual control.
      checkButton.title = error.message;
      if (manual) pop(error.message);
    } finally {
      checking = false; lastCheck = Date.now();
      checkButton.disabled = false; checkButton.textContent = 'Check photos';
    }
  }

  function showMessage(text, detail = '') {
    picture.hidden = true;
    message.replaceChildren();
    const title = document.createElement('span'); title.textContent = text; message.append(title);
    if (detail) { const small = document.createElement('small'); small.textContent = detail; message.append(small); }
    message.hidden = false;
  }

  function showSlide() {
    const token = ++generation;
    if (index < 0 || index >= sequence.length) {
      picture.removeAttribute('src');
      showMessage('Leave photo viewer');
      previous.setAttribute('aria-label', 'Leave photo viewer');
      next.setAttribute('aria-label', 'Leave photo viewer');
      return;
    }
    previous.setAttribute('aria-label', 'Previous photo'); next.setAttribute('aria-label', 'Next photo');
    showMessage('Loading photo…');
    picture.onload = () => {
      if (!open || token !== generation) return;
      message.hidden = true; picture.hidden = false;
      // Preload only the next preview. The displayed list remains fixed until closed.
      if (sequence[index + 1]) { const preload = new Image(); preload.src = sequence[index + 1].url; }
    };
    picture.onerror = () => {
      if (open && token === generation) showMessage('Photo unavailable', 'Tap left or right to continue, or press Escape to leave.');
    };
    picture.src = sequence[index].url;
  }

  function closeViewer() {
    if (!open) return;
    open = false; ++generation; sequence = [];
    viewer.hidden = true; picture.removeAttribute('src');
    document.body.classList.remove('viewer-open');
    document.querySelector('header').inert = false; document.querySelector('main').inert = false;
    if (document.fullscreenElement === viewer) document.exitFullscreen().catch(() => {});
    originButton?.focus({preventScroll:true});
  }

  async function fetchViewerPhotos(button) {
    const job = all.find(j => j.id === Number(button.dataset.photos));
    if (!job) return;
    // Unsaved edits must not silently select a different photo window.
    const state = await api('/api/state');
    const saved = state.jobs.find(j => j.id === job.id);
    if (!saved || key(saved) !== key(job)) { pop('Save day before checking photos for edited times.'); return; }
    return checkJob(job);
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-photos]');
    if (!button || open) return;
    open = true; originButton = button; sequence = []; index = 0;
    viewer.hidden = false; document.body.classList.add('viewer-open');
    showMessage('Checking photos…');
    document.querySelector('header').inert = true; document.querySelector('main').inert = true;
    previous.focus({preventScroll:true});
    // Must run in the click gesture, before any network await (mobile browsers).
    actualFullscreen = false;
    if (viewer.requestFullscreen) viewer.requestFullscreen().then(() => {
      actualFullscreen = true;
      if (!open && document.fullscreenElement === viewer) document.exitFullscreen().catch(() => {});
    }).catch(() => {});
    const token = ++generation;
    try {
      const result = await fetchViewerPhotos(button);
      if (!open || token !== generation) return;
      if (!result) { closeViewer(); return; }
      sequence = result.photos;
      if (!sequence.length) {
        index = -1;
        showMessage('Leave photo viewer', 'No photos found within this job’s saved times.');
      } else { index = 0; showSlide(); }
    } catch (error) {
      if (!open || token !== generation) return;
      index = -1; showMessage('Leave photo viewer', error.message);
    }
  });

  function move(delta) {
    if (!open) return;
    if (index < 0 || index >= sequence.length) { closeViewer(); return; }
    index += delta; showSlide();
  }
  previous.addEventListener('click', () => move(-1)); next.addEventListener('click', () => move(1));
  document.addEventListener('keydown', event => {
    if (!open) return;
    if (event.key === 'Escape') { event.preventDefault(); closeViewer(); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); move(-1); }
    if (event.key === 'ArrowRight') { event.preventDefault(); move(1); }
    if (event.key === 'Tab') { event.preventDefault(); (document.activeElement === previous ? next : previous).focus(); }
  });
  document.addEventListener('fullscreenchange', () => {
    if (actualFullscreen && !document.fullscreenElement) { actualFullscreen = false; closeViewer(); }
  });
  checkButton.addEventListener('click', () => checkDay(true));
  day.addEventListener('change', () => { lastCheck = 0; paintCounts(); });
  document.getElementById('save').addEventListener('click', () => { counts.clear(); lastCheck = 0; paintCounts(); });
  api('/api/photos/settings').then(value => { config = value; }).catch(() => {});
  setInterval(() => {
    if (config?.configured && config.interval > 0 && Date.now() - lastCheck >= config.interval * 60000) checkDay();
  }, 15000);
})();
