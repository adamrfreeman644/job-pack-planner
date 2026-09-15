"""Server-side Immich access. Credentials never enter photo URLs or public state."""
from datetime import datetime, timedelta, timezone
from functools import wraps
from hashlib import sha256
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import io
import json
import re
import socket
import time

from flask import jsonify, request, send_file

DEFAULTS = {'url': '', 'timezone': 'Europe/London', 'margin': 0, 'interval': 5}
ASSET_ID = re.compile(r'^[a-fA-F0-9-]{36}$')


class PhotoError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(req.full_url)[:2] != urlsplit(newurl)[:2]:
            raise PhotoError('Immich redirected to another server. Check the address in Settings.', 502)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalise_url(value):
    value = str(value).strip().rstrip('/')
    parts = urlsplit(value)
    if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment or any(c.isspace() for c in value)):
        raise PhotoError('Enter an HTTP or HTTPS Immich address without credentials or query parameters.')
    try:
        parts.port
    except ValueError:
        raise PhotoError('The Immich port is invalid.')
    return value if parts.path.endswith('/api') else value + '/api'


def immich_request(config, path, body=None, image=False):
    if not config.get('url') or not config.get('key'):
        raise PhotoError('Connect Immich in Settings first.', 409)
    headers = {'x-api-key': config['key'], 'Accept': 'image/*' if image else 'application/json'}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    req = Request(config['url'] + path, data=data, headers=headers)
    try:
        with build_opener(SameOriginRedirect()).open(req, timeout=15) as response:
            limit = 32 * 1024 * 1024 if image else 8 * 1024 * 1024
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise PhotoError('The Immich response is too large.', 502)
            if image:
                mime = response.headers.get_content_type()
                if mime not in {'image/jpeg', 'image/png', 'image/webp', 'image/avif', 'image/gif'}:
                    raise PhotoError('Immich did not return a supported photo preview.', 502)
                return raw, mime
            return json.loads(raw)
    except HTTPError as error:
        if error.code in (401, 403):
            raise PhotoError('Immich refused access. Check the API key and its photo permissions in Settings.', 502)
        raise PhotoError('Immich could not complete the request. Check the connection and server version.', 502)
    except (URLError, socket.timeout, TimeoutError, OSError):
        raise PhotoError('Cannot reach Immich. Check its address and that the server is running.', 502)
    except (ValueError, UnicodeError):
        raise PhotoError('Immich returned an unexpected response.', 502)


def job_window(job, config):
    try:
        zone = ZoneInfo(config['timezone'])
        start = datetime.fromisoformat(job['day'] + 'T' + job['start'])
        end = datetime.fromisoformat(job['day'] + 'T' + job['finish'])
        if end == start:
            raise PhotoError('Set different arrival and departure times, then save the day.')
        if end < start:
            end += timedelta(days=1)
        def localise(value, fold):
            aware = value.replace(tzinfo=zone, fold=fold)
            if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != value:
                raise PhotoError('A job time falls in the daylight-saving clock change. Adjust and save it.')
            return aware.astimezone(timezone.utc)
        margin = timedelta(minutes=int(config['margin']))
        return localise(start, 0) - margin, localise(end, 1) + margin
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise PhotoError('Check the saved job date, times and photo timezone in Settings.')


def search_photos(config, start, end):
    found = {}
    page = 1
    deadline = time.monotonic() + 45
    for _ in range(100):
        result = immich_request(config, '/search/metadata', {
            'type': 'IMAGE', 'takenAfter': start.isoformat(), 'takenBefore': end.isoformat(),
            'withDeleted': False, 'withStacked': True, 'order': 'asc', 'size': 1000, 'page': page,
        })
        assets = result.get('assets') if isinstance(result, dict) else None
        if not isinstance(assets, dict) or not isinstance(assets.get('items'), list):
            raise PhotoError('Immich returned an unexpected photo list.', 502)
        for asset in assets['items']:
            if not isinstance(asset, dict):
                continue
            aid = str(asset.get('id', ''))
            if asset.get('type') != 'IMAGE' or asset.get('isTrashed') or not ASSET_ID.fullmatch(aid):
                continue
            try:
                taken = datetime.fromisoformat(asset['fileCreatedAt'].replace('Z', '+00:00'))
                if taken.tzinfo is None or not start <= taken <= end:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            found[aid] = {'id': aid, 'taken': taken.astimezone(timezone.utc).isoformat()}
        next_page = assets.get('nextPage')
        if next_page is None:
            return sorted(found.values(), key=lambda asset: (asset['taken'], asset['id']))
        try:
            next_page = int(next_page)
            if next_page <= page:
                raise ValueError()
        except (ValueError, TypeError):
            raise PhotoError('Immich returned an invalid next page.', 502)
        page = next_page
        if time.monotonic() > deadline:
            break
    raise PhotoError('There are too many photos to check at once. Reduce the job time range.', 502)


def register_photos(app, db):
    def config_read():
        c = db()
        values = {r['k'][7:]: r['v'] for r in c.execute("SELECT k,v FROM settings WHERE k LIKE 'immich_%'")}
        c.close()
        config = {**DEFAULTS, **values}
        config['margin'] = int(config['margin'])
        config['interval'] = int(config['interval'])
        return config

    def public(config):
        return {**{k: config[k] for k in DEFAULTS}, 'has_key': bool(config.get('key')),
                'configured': bool(config.get('url') and config.get('key'))}

    def protected(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                if request.method == 'POST':
                    origin = request.headers.get('Origin')
                    if (origin and origin != request.host_url.rstrip('/')) or not request.is_json:
                        raise PhotoError('Use the planner to submit this request.', 403)
                response = app.make_response(fn(*args, **kwargs))
            except PhotoError as error:
                response = jsonify(error=str(error))
                response.status_code = error.status
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        return wrapped

    def job_read(job_id):
        c = db()
        row = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        c.close()
        if row is None:
            raise PhotoError('This job no longer exists.', 404)
        return dict(row)

    def fingerprint(config, start, end):
        return sha256(json.dumps([config, start.isoformat(), end.isoformat()], sort_keys=True).encode()).hexdigest()

    def cache_db():
        c = db()
        c.execute('CREATE TABLE IF NOT EXISTS photo_checks(job_id INTEGER PRIMARY KEY, fingerprint TEXT, assets TEXT, checked TEXT)')
        return c

    @app.get('/api/photos/settings')
    @protected
    def photo_settings():
        return jsonify(public(config_read()))

    @app.post('/api/photos/settings')
    @protected
    def save_photo_settings():
        body = request.get_json()
        if not isinstance(body, dict):
            raise PhotoError('Invalid settings.')
        old = config_read()
        url = normalise_url(body.get('url', '')) if body.get('url') else ''
        key = str(body.get('key', '')).strip()
        if any(ord(ch) < 32 for ch in key) or len(key) > 4096:
            raise PhotoError('The API key is invalid.')
        if url != old['url'] and not key:
            # Never send an existing server's credential to a newly entered address.
            key = ''
        elif not key and not body.get('clear_key'):
            key = old.get('key', '')
        if body.get('clear_key'):
            key = ''
        try:
            zone = str(body.get('timezone', DEFAULTS['timezone']))
            ZoneInfo(zone)
            margin = int(body.get('margin', 0))
            interval = int(body.get('interval', 5))
            if not 0 <= margin <= 120 or interval not in {0, 1, 5, 10, 15, 30, 60}:
                raise ValueError()
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            raise PhotoError('Choose a valid timezone, allowance (0–120 minutes) and refresh interval.')
        config = {'url': url, 'key': key, 'timezone': zone, 'margin': margin, 'interval': interval}
        c = cache_db()
        with c:
            for k, v in config.items():
                c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)', ('immich_' + k, str(v)))
            c.execute('DELETE FROM photo_checks')
        c.close()
        return jsonify(public(config))

    @app.post('/api/photos/test')
    @protected
    def test_photo_connection():
        config = config_read()
        result = immich_request(config, '/search/metadata', {'type': 'IMAGE', 'size': 1, 'page': 1})
        assets = result.get('assets') if isinstance(result, dict) else None
        if not isinstance(assets, dict) or not isinstance(assets.get('items'), list):
            raise PhotoError('Immich returned an unexpected response.', 502)
        items = assets['items']
        if items:
            if not isinstance(items[0], dict):
                raise PhotoError('Immich returned an invalid photo.', 502)
            aid = str(items[0].get('id', ''))
            if not ASSET_ID.fullmatch(aid):
                raise PhotoError('Immich returned an invalid photo.', 502)
            immich_request(config, '/assets/' + aid + '/thumbnail?size=preview', image=True)
        return jsonify(ok=True, message='Connected. Photo search and preview work.' if items else
                       'Connected. Photo search works; upload a photo to test previews.')

    @app.post('/api/jobs/<int:job_id>/photos/check')
    @protected
    def check_job_photos(job_id):
        config = config_read()
        start, end = job_window(job_read(job_id), config)
        photos = search_photos(config, start, end)
        checked = datetime.now(timezone.utc).isoformat()
        c = cache_db()
        with c:
            c.execute('INSERT OR REPLACE INTO photo_checks VALUES(?,?,?,?)',
                      (job_id, fingerprint(config, start, end), json.dumps(photos), checked))
        c.close()
        return jsonify(photos=[{'id': p['id'], 'url': f"/api/jobs/{job_id}/photos/{p['id']}"} for p in photos],
                       count=len(photos), checked=checked)

    @app.get('/api/jobs/<int:job_id>/photos/<asset_id>')
    @protected
    def photo_preview(job_id, asset_id):
        config = config_read()
        start, end = job_window(job_read(job_id), config)
        c = cache_db()
        row = c.execute('SELECT * FROM photo_checks WHERE job_id=?', (job_id,)).fetchone()
        c.close()
        if (not ASSET_ID.fullmatch(asset_id) or row is None
                or row['fingerprint'] != fingerprint(config, start, end)
                or asset_id not in {p['id'] for p in json.loads(row['assets'])}):
            raise PhotoError('Check this job for photos again.', 404)
        raw, mime = immich_request(config, '/assets/' + asset_id + '/thumbnail?size=preview', image=True)
        return send_file(io.BytesIO(raw), mimetype=mime)
