"""Optional Google route planning for the day planner."""
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import socket

from flask import jsonify, request


class RouteError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _google_request(api_key, origin, destination, stops, optimise):
    body = {
        'origin': {'address': origin},
        'destination': {'address': destination},
        'intermediates': [{'address': stop['address']} for stop in stops],
        'travelMode': 'DRIVE',
        'routingPreference': 'TRAFFIC_AWARE',
        'computeAlternativeRoutes': False,
        'languageCode': 'en-GB',
        'regionCode': 'gb',
        'units': 'IMPERIAL',
    }
    if optimise and len(stops) > 1:
        body['optimizeWaypointOrder'] = True
    fields = ('routes.optimizedIntermediateWaypointIndex,routes.legs.duration,'
              'routes.legs.distanceMeters,routes.duration,routes.distanceMeters')
    req = Request(
        'https://routes.googleapis.com/directions/v2:computeRoutes',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'X-Goog-Api-Key': api_key,
                 'X-Goog-FieldMask': fields},
        method='POST',
    )
    try:
        with urlopen(req, timeout=20) as response:
            data = json.loads(response.read(2 * 1024 * 1024))
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get('error', {}).get('message', '')
        except Exception:
            detail = ''
        if error.code in {401, 403}:
            raise RouteError('Google refused the route request. Check the API key, billing and Routes API settings.', 502)
        raise RouteError(detail or 'Google could not calculate this route.', 502)
    except (URLError, socket.timeout, TimeoutError, OSError, ValueError):
        raise RouteError('Google Routes could not be reached. Try again shortly.', 502)
    routes = data.get('routes') if isinstance(data, dict) else None
    if not routes:
        raise RouteError('No driving route was found for these addresses.', 422)
    return routes[0]


def _seconds(value):
    try:
        return round(float(str(value).rstrip('s')))
    except (TypeError, ValueError):
        return 0


def _minutes(value):
    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute


def _optimise_with_locks(api_key, home, jobs, locked_ids):
    if len(jobs) < 2:
        return jobs
    locked_positions = [i for i, job in enumerate(jobs) if job['id'] in locked_ids]
    if not locked_positions:
        route = _google_request(api_key, home, home, jobs, True)
        order = route.get('optimizedIntermediateWaypointIndex', list(range(len(jobs))))
        return [jobs[i] for i in order]

    result = []
    boundaries = [-1] + locked_positions + [len(jobs)]
    for boundary_index in range(len(boundaries) - 1):
        left, right = boundaries[boundary_index], boundaries[boundary_index + 1]
        segment = jobs[left + 1:right]
        origin = home if left < 0 else jobs[left]['address']
        destination = home if right >= len(jobs) else jobs[right]['address']
        if len(segment) > 1:
            route = _google_request(api_key, origin, destination, segment, True)
            order = route.get('optimizedIntermediateWaypointIndex', list(range(len(segment))))
            segment = [segment[i] for i in order]
        result.extend(segment)
        if right < len(jobs):
            result.append(jobs[right])
    return result


def register_routes(app, db):
    def setting_values():
        c = db()
        values = {row['k']: row['v'] for row in c.execute(
            "SELECT k,v FROM settings WHERE k IN ('home_address','google_routes_api_key')")}
        c.close()
        return values

    def json_body():
        if not request.is_json:
            raise RouteError('Use the planner to submit this request.', 415)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise RouteError('Invalid route request.')
        return body

    def reply(fn):
        try:
            response = app.make_response(fn())
        except RouteError as error:
            response = jsonify(error=str(error))
            response.status_code = error.status
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/api/route/settings')
    def route_settings():
        def action():
            values = setting_values()
            return jsonify(home_address=values.get('home_address', ''),
                           has_api_key=bool(values.get('google_routes_api_key')))
        return reply(action)

    @app.post('/api/route/settings')
    def save_route_settings():
        def action():
            body = json_body()
            home = str(body.get('home_address', '')).strip()
            key = str(body.get('api_key', '')).strip()
            if len(home) > 500 or len(key) > 4096 or any(ord(ch) < 32 for ch in key):
                raise RouteError('The route settings are invalid.')
            c = db()
            c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)', ('home_address', home))
            if body.get('clear_api_key'):
                c.execute("DELETE FROM settings WHERE k='google_routes_api_key'")
            elif key:
                c.execute('INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)', ('google_routes_api_key', key))
            c.commit(); c.close()
            values = setting_values()
            return jsonify(home_address=values.get('home_address', ''),
                           has_api_key=bool(values.get('google_routes_api_key')))
        return reply(action)

    @app.post('/api/route/plan')
    def plan_route():
        def action():
            body = json_body()
            raw_ids = body.get('job_ids', [])
            if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 25:
                raise RouteError('Choose between 1 and 25 jobs to plan.')
            try:
                ids = [int(value) for value in raw_ids]
                locked_ids = {int(value) for value in body.get('locked_ids', [])}
            except (TypeError, ValueError):
                raise RouteError('The selected jobs are invalid.')
            if len(ids) != len(set(ids)):
                raise RouteError('A job was included more than once.')
            values = setting_values(); home = values.get('home_address', '').strip()
            api_key = values.get('google_routes_api_key', '').strip()
            if not home:
                raise RouteError('Add your home or start address in Settings first.', 409)
            if not api_key:
                raise RouteError('Add a Google Routes API key in Settings to optimise the day.', 409)
            c = db()
            placeholders = ','.join('?' for _ in ids)
            rows = list(c.execute(f'SELECT * FROM jobs WHERE id IN ({placeholders})', ids))
            c.close()
            by_id = {row['id']: row for row in rows}
            if len(by_id) != len(ids):
                raise RouteError('One of these jobs no longer exists.', 404)
            jobs = []
            for job_id in ids:
                row = by_id[job_id]
                details = json.loads(row['details'] or '{}')
                address = (details.get('Site Address') or row['postcode'] or '').strip()
                if not address:
                    raise RouteError(f"Job {row['job_no']} has no site address.", 422)
                jobs.append({'id': row['id'], 'job_no': row['job_no'], 'address': address,
                             'start': row['start'], 'finish': row['finish']})
            ordered = _optimise_with_locks(api_key, home, jobs, locked_ids)
            final_route = _google_request(api_key, home, home, ordered, False)
            raw_legs = final_route.get('legs', [])
            legs = []
            for i, leg in enumerate(raw_legs):
                duration_seconds = _seconds(leg.get('duration'))
                warning = ''
                if i < len(ordered):
                    depart = body.get('leave_home', '07:00') if i == 0 else ordered[i - 1]['finish']
                    arrive = ordered[i]['start']
                    try:
                        available = _minutes(arrive) - _minutes(depart)
                        if available < 0: available += 24 * 60
                        if duration_seconds > available * 60:
                            warning = f"Needs about {round(duration_seconds / 60)} min; only {available} min allowed"
                    except (ValueError, TypeError):
                        pass
                legs.append({
                    'from_id': None if i == 0 else ordered[i - 1]['id'],
                    'to_id': None if i >= len(ordered) else ordered[i]['id'],
                    'duration_minutes': max(1, round(duration_seconds / 60)),
                    'distance_miles': round(float(leg.get('distanceMeters', 0)) / 1609.344, 1),
                    'warning': warning,
                })
            return jsonify(
                ordered_ids=[job['id'] for job in ordered], legs=legs,
                duration_minutes=max(1, round(_seconds(final_route.get('duration')) / 60)),
                distance_miles=round(float(final_route.get('distanceMeters', 0)) / 1609.344, 1),
            )
        return reply(action)
