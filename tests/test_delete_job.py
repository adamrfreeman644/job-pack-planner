import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class DeleteJobTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        with patch.dict(os.environ, {'JOB_PACK_DATA': self.folder.name}):
            self.module = importlib.import_module('app')
        self.db_patch = patch.object(self.module, 'DB', Path(self.folder.name) / 'planner.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.client = self.module.app.test_client()
        c = self.module.db()
        with c:
            for job_id, day in [(1, '2026-10-15'), (2, '2026-10-15'), (3, '2026-10-16')]:
                c.execute("INSERT INTO jobs(id,job_no,day,start,finish,position,details) VALUES(?,'FJ123',?,'09:00','10:00',?,'{}')", (job_id, day, job_id))
                c.execute('INSERT INTO job_materials VALUES(?,?)', (job_id, 'Materials'))
            c.execute('CREATE TABLE photo_checks(job_id INTEGER PRIMARY KEY, fingerprint TEXT, assets TEXT, checked TEXT)')
            c.execute("INSERT INTO photo_checks VALUES(1,'test','[]','today')")
            for day in ['2026-10-15', '2026-10-16']:
                c.execute('INSERT INTO day_settings VALUES(?,?,?)', (day, '07:00', '17:00'))
                c.execute('INSERT INTO settings VALUES(?,?)', ('route_plan:' + day, json.dumps({'day': day, 'items': [{'type': 'job', 'id': 1}], 'stops': [{'label': 'Colleague'}], 'geometry': [[1, 2]]})))
        c.close()

    def test_delete_persists_and_only_removes_selected_visit(self):
        self.assertEqual(self.client.delete('/api/jobs/1').status_code, 200)
        state = self.client.get('/api/state').json
        self.assertEqual([job['id'] for job in state['jobs']], [2, 3])
        self.assertTrue(all(job['materials'] == 'Materials' for job in state['jobs']))
        self.assertEqual(len(state['day_settings']), 2)
        c = self.module.db()
        self.assertIsNone(c.execute('SELECT * FROM job_materials WHERE job_id=1').fetchone())
        self.assertIsNone(c.execute('SELECT * FROM photo_checks WHERE job_id=1').fetchone())
        c.close()
        route = self.client.get('/api/route/day/2026-10-15').json
        self.assertEqual(route['items'], [])
        self.assertEqual(route['stops'], [{'label': 'Colleague'}])
        self.assertNotIn('geometry', route)
        self.assertTrue(self.client.get('/api/route/day/2026-10-16').json['items'])

    def test_missing_job_returns_404_without_touching_other_jobs(self):
        self.assertEqual(self.client.delete('/api/jobs/999').status_code, 404)
        self.assertEqual(len(self.client.get('/api/state').json['jobs']), 3)

    def test_delete_works_before_any_photo_check(self):
        c = self.module.db()
        c.execute('DROP TABLE photo_checks')
        c.commit()
        c.close()
        self.assertEqual(self.client.delete('/api/jobs/1').status_code, 200)


if __name__ == '__main__':
    unittest.main()
