"""Process health must remain fresh while bounded auxiliary work is active."""
import threading
import unittest
from unittest.mock import Mock, patch
from backend.worker import Worker

class ResearchWorkerHealthTests(unittest.TestCase):
    def test_research_health_continues_and_stops_when_work_ends(self):
        worker=Worker(Mock(),lease=0.03)
        worker.jobs=Mock();worker.jobs.claim.return_value=None
        tick=threading.Event();worker.online=Mock(side_effect=lambda:tick.set())
        def research():
            tick.clear()
            self.assertTrue(tick.wait(1), 'heartbeat missing during research')
            return True
        with patch('backend.research_jobs.ResearchJobs') as factory:
            factory.return_value.once.side_effect=research
            self.assertTrue(worker.once())
        calls=worker.online.call_count
        self.assertGreaterEqual(calls,2)
        tick.clear()
        self.assertFalse(tick.wait(0.06), 'heartbeat leaked beyond auxiliary work')
        self.assertEqual(worker.online.call_count,calls)
        worker.jobs.heartbeat.assert_not_called()
