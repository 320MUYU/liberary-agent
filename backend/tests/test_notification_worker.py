"""The worker health signal advances only after a successful database scan."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import notification_worker


class NotificationWorkerTest(unittest.TestCase):
    def test_success_records_completed_scan_and_process(self):
        with TemporaryDirectory() as directory:
            heartbeat = Path(directory) / 'notifications' / 'heartbeat.json'
            with patch.object(notification_worker, 'HEARTBEAT', heartbeat), \
                    patch.object(notification_worker, 'SessionLocal'), \
                    patch.object(notification_worker, 'generate_reminders', return_value=2), \
                    patch.object(notification_worker.time, 'time', return_value=1234):
                self.assertEqual(notification_worker.run_once(), 2)
            self.assertEqual(json.loads(heartbeat.read_text()), {'pid': os.getpid(), 'success_at': 1234, 'created': 2})
            self.assertFalse(heartbeat.with_suffix('.tmp').exists())

    def test_failure_keeps_last_success_instead_of_reporting_healthy(self):
        with TemporaryDirectory() as directory:
            heartbeat = Path(directory) / 'heartbeat.json'
            heartbeat.write_text('{"success_at": 100}')
            with patch.object(notification_worker, 'HEARTBEAT', heartbeat), \
                    patch.object(notification_worker, 'SessionLocal'), \
                    patch.object(notification_worker, 'generate_reminders', side_effect=RuntimeError('database unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'database unavailable'):
                    notification_worker.run_once()
            self.assertEqual(json.loads(heartbeat.read_text()), {'success_at': 100})
