import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.request import Request

import photos


A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'
C = '33333333-3333-4333-8333-333333333333'
CONFIG = {'url': 'http://immich:2283/api', 'key': 'private-test-key',
          'timezone': 'Europe/London', 'margin': 0, 'interval': 5}


def asset(aid, taken, **extra):
    return {'id': aid, 'type': 'IMAGE', 'fileCreatedAt': taken, **extra}


class PhotoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory()
        os.environ['JOB_PACK_DATA'] = cls.root.name
        cls.module = importlib.import_module('app')

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.module.DB = Path(self.folder.name) / 'planner.db'
        self.module.MASTER = Path(self.folder.name) / 'master.xml'
        self.client = self.module.app.test_client()
        c = self.module.db()
        with c:
            c.execute("INSERT INTO jobs(id,job_no,day,start,finish,position,details) VALUES(1,'J1','2026-09-15','09:00','10:00',0,'{}')")
            for k, v in CONFIG.items():
                c.execute('INSERT INTO settings(k,v) VALUES(?,?)', ('immich_' + k, str(v)))
        c.close()

    def test_timezone_summer_winter_overnight_and_margin(self):
        start, end = photos.job_window({'day':'2026-09-15','start':'09:00','finish':'10:00'}, CONFIG)
        self.assertEqual(start.isoformat(), '2026-09-15T08:00:00+00:00')
        self.assertEqual(end.hour, 9)
        start, end = photos.job_window({'day':'2026-12-15','start':'23:30','finish':'01:00'}, {**CONFIG, 'margin': 10})
        self.assertEqual(start.isoformat(), '2026-12-15T23:20:00+00:00')
        self.assertEqual(end.isoformat(), '2026-12-16T01:10:00+00:00')

    def test_dst_gap_rejected_and_overlap_included(self):
        with self.assertRaises(photos.PhotoError):
            photos.job_window({'day':'2026-03-29','start':'01:30','finish':'03:00'}, CONFIG)
        start, end = photos.job_window({'day':'2026-10-25','start':'01:10','finish':'01:50'}, CONFIG)
        self.assertEqual((end - start).total_seconds(), 100 * 60)

    def test_invalid_and_equal_times(self):
        for start, end in [('', '10:00'), ('09:00', '09:00')]:
            with self.assertRaises(photos.PhotoError):
                photos.job_window({'day':'2026-09-15','start':start,'finish':end}, CONFIG)

    def test_pagination_order_boundaries_and_filtering(self):
        results = [
            {'assets': {'items': [asset(B, '2026-09-15T09:00:00Z'), asset(C, '2026-09-15T07:59:59Z'),
                                  asset(A, '2026-09-15T08:00:00Z', type='VIDEO')], 'nextPage':'2'}},
            {'assets': {'items': [asset(A, '2026-09-15T08:00:00Z'), asset(B, '2026-09-15T09:00:00Z'),
                                  asset(C, '2026-09-15T08:30:00Z', isTrashed=True)], 'nextPage':None}},
        ]
        with patch('photos.immich_request', side_effect=results) as call:
            start, end = photos.job_window({'day':'2026-09-15','start':'09:00','finish':'10:00'}, CONFIG)
            found = photos.search_photos(CONFIG, start, end)
        self.assertEqual([a['id'] for a in found], [A, B])
        self.assertEqual(call.call_args_list[1].args[2]['page'], 2)
        self.assertEqual(call.call_args_list[0].args[2]['takenAfter'], '2026-09-15T08:00:00+00:00')

    def test_bad_pagination_is_error_not_partial_success(self):
        with patch('photos.immich_request', return_value={'assets': {'items': [], 'nextPage':'1'}}):
            with self.assertRaises(photos.PhotoError):
                photos.search_photos(CONFIG, datetime.now(timezone.utc), datetime.now(timezone.utc))

    def test_key_never_returned_or_overwritten_by_general_save(self):
        for path in ['/api/state', '/api/photos/settings']:
            response = self.client.get(path)
            self.assertNotIn(CONFIG['key'], response.get_data(as_text=True))
        self.client.post('/api/save', json={'day':'', 'jobs':[], 'settings':{'immich_key':'attack'}})
        c = self.module.db()
        self.assertEqual(c.execute("SELECT v FROM settings WHERE k='immich_key'").fetchone()[0], CONFIG['key'])
        c.close()

    def test_settings_preserve_blank_key_but_clear_on_server_change(self):
        body = {**CONFIG, 'key':''}
        response = self.client.post('/api/photos/settings', json=body)
        self.assertTrue(response.json['has_key'])
        response = self.client.post('/api/photos/settings', json={**body, 'url':'https://another-server'})
        self.assertFalse(response.json['has_key'])
        self.assertEqual(response.json['url'], 'https://another-server/api')

    def test_https_browser_through_http_reverse_proxy(self):
        headers = {'Origin':'https://jobpack.example.com', 'Sec-Fetch-Site':'same-origin'}
        response = self.client.post('/api/photos/settings', base_url='http://jobpack.example.com',
                                    headers=headers, json={**CONFIG, 'key':''})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['has_key'])
        with patch('photos.immich_request', return_value={'assets':{'items':[]}}):
            response = self.client.post('/api/photos/test', base_url='http://jobpack.example.com',
                                        headers=headers, json={})
        self.assertEqual(response.status_code, 200)
        with patch('photos.search_photos', return_value=[]):
            response = self.client.post('/api/jobs/1/photos/check', base_url='http://jobpack.example.com',
                                        headers=headers, json={})
        self.assertEqual(response.status_code, 200)

    def test_proxy_support_still_rejects_cross_origin_requests(self):
        for origin, site in [('https://other.example.com','same-site'),
                             ('https://evil.example','cross-site'),
                             ('https://evil.example','same-origin'),
                             ('null','same-origin'),
                             ('https://jobpack.example.com','same-site')]:
            response = self.client.post('/api/photos/settings', base_url='http://jobpack.example.com',
                headers={'Origin':origin, 'Sec-Fetch-Site':site}, json=CONFIG)
            self.assertEqual(response.status_code, 403, (origin, site))

    def test_invalid_settings_and_cross_origin_rejected(self):
        for override in [{'timezone':'No/Such'}, {'margin':121}, {'interval':2}, {'url':'file:///etc/passwd'}]:
            response = self.client.post('/api/photos/settings', json={**CONFIG, **override})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/photos/settings', json=CONFIG, headers={'Origin':'https://elsewhere'}).status_code, 403)
        self.assertEqual(self.client.post('/api/photos/settings', data='{}').status_code, 403)

    def test_check_and_preview_are_scoped_to_job_and_current_settings(self):
        with patch('photos.search_photos', return_value=[{'id':A, 'taken':'2026-09-15T08:30:00+00:00'}]):
            response = self.client.post('/api/jobs/1/photos/check', json={})
        self.assertEqual(response.json['count'], 1)
        with patch('photos.immich_request', return_value=(b'preview', 'image/jpeg')) as call:
            response = self.client.get('/api/jobs/1/photos/' + A)
            self.assertEqual(response.data, b'preview')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(self.client.get('/api/jobs/1/photos/' + B).status_code, 404)
            self.assertEqual(call.call_count, 1)
            self.client.post('/api/save', json={'day':'2026-09-15','jobs':[{'id':1,'start':'12:00','finish':'13:00'}]})
            self.assertEqual(self.client.get('/api/jobs/1/photos/' + A).status_code, 404)

    def test_empty_missing_job_and_connection_error(self):
        with patch('photos.search_photos', return_value=[]):
            self.assertEqual(self.client.post('/api/jobs/1/photos/check', json={}).json['photos'], [])
            self.assertEqual(self.client.post('/api/jobs/999/photos/check', json={}).status_code, 404)
        with patch('photos.immich_request', side_effect=photos.PhotoError('Cannot reach Immich.', 502)):
            self.assertEqual(self.client.post('/api/jobs/1/photos/check', json={}).status_code, 502)

    def test_connection_test_checks_preview_permission(self):
        with patch('photos.immich_request', side_effect=[{'assets':{'items':[asset(A, '2026-09-15T08:30:00Z')]}}, (b'jpeg','image/jpeg')]) as call:
            self.assertEqual(self.client.post('/api/photos/test', json={}).status_code, 200)
            self.assertEqual(call.call_count, 2)

    def test_redirect_cannot_leak_key_to_other_host(self):
        req = Request('http://immich:2283/api/assets/id/thumbnail', headers={'x-api-key':CONFIG['key']})
        with self.assertRaises(photos.PhotoError):
            photos.SameOriginRedirect().redirect_request(req, None, 302, '', {}, 'https://another-host/photo')

    def test_existing_day_save_and_xml_export_still_work(self):
        root = ET.Element('form')
        record = ET.SubElement(root, 'record')
        for name in ['Job No.', 'Arrive Site', 'Depart Site', 'Depart Time', 'Arrive Next', 'Lead Engineer']:
            ET.SubElement(record, 'field', name=name)
        ET.ElementTree(root).write(self.module.MASTER)
        response = self.client.post('/api/save', json={'day':'2026-09-15',
            'jobs':[{'id':1,'start':'09:15','finish':'10:30'}],
            'settings':{'leave_home':'08:00','return_home':'17:00','resources':'Test Engineer'}})
        self.assertEqual(response.status_code, 200)
        with patch('app.nearest_ae', return_value='Hospital'):
            response = self.client.get('/api/export/1')
        self.assertEqual(response.status_code, 200)
        fields = {f.get('name'):f.text for f in ET.fromstring(response.data).find('record')}
        self.assertEqual(fields['Arrive Site'], '09:15')
        self.assertEqual(fields['Depart Site'], '10:30')
        self.assertEqual(fields['Depart Time'], '08:00')
        self.assertEqual(fields['Arrive Next'], '17:00')
        self.assertEqual(fields['Lead Engineer'], 'Test')


if __name__ == '__main__':
    unittest.main()
