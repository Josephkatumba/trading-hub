import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ops import control
from ops.watchdog import Watchdog

class ControlTests(unittest.TestCase):
    def test_persisted_intent_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'STATE_FILE', Path(directory)/'state.json'):
            self.assertEqual(control.read_state()['state'], 'STOPPED')
            for state in ('RUNNING', 'PAUSED', 'STOPPED'):
                control.set_state(state)
                self.assertEqual(control.read_state()['state'], state)
            control.STATE_FILE.write_text('broken')
            self.assertEqual(control.read_state()['state'], 'STOPPED')

    def test_failure_cannot_overwrite_owner_stop(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'STATE_FILE', Path(directory)/'state.json'):
            control.set_state('STOPPED')
            control.set_state('PAUSED', 'late connection failure', expected='RUNNING')
            self.assertEqual(control.read_state()['state'], 'STOPPED')

    def test_pause_stop_never_probe_or_launch(self):
        def forbidden():
            self.fail('Inactive manager touched engine')
        for state in ('PAUSED', 'STOPPED'):
            dog = Watchdog(probe_port=forbidden, launcher=forbidden, intent=lambda: {'state': state})
            for _ in range(10):
                self.assertEqual(dog.tick(), state)


class EngineRunnerTests(unittest.TestCase):
    def test_stop_never_starts_server(self):
        from ops import engine
        with patch.object(engine, 'read_state', return_value={'state': 'STOPPED'}), patch.object(engine, 'single_instance_lock') as lock, patch.object(engine.uvicorn, 'Server') as server:
            engine.main()
            server.assert_not_called()
            lock.return_value.close.assert_called_once()

    def test_unexpected_exception_preserves_recovery_intent(self):
        from ops import engine
        with patch.object(engine, 'read_state', return_value={'state': 'RUNNING'}), patch.object(engine, 'single_instance_lock'), patch.object(engine.uvicorn, 'Server') as server, patch.object(engine, 'set_state') as write:
            server.return_value.run.side_effect = RuntimeError('unexpected crash')
            with self.assertRaises(RuntimeError):
                engine.main()
            write.assert_not_called()

    def test_normal_exit_disables_recovery(self):
        from ops import engine
        states = iter([{'state': 'RUNNING'}, {'state': 'RUNNING'}, {'state': 'RUNNING'}, {'state': 'STOPPED'}])
        with patch.object(engine, 'read_state', side_effect=lambda: next(states)), patch.object(engine, 'single_instance_lock'), patch.object(engine.uvicorn, 'Server'), patch.object(engine, 'set_state') as write:
            engine.main()
            write.assert_called_once_with('STOPPED', 'Engine exited normally; explicit start required', expected='RUNNING')


    def test_keyboard_interrupt_is_intentional_shutdown(self):
        from ops import engine
        with patch.object(engine, 'read_state', return_value={'state': 'RUNNING'}), patch.object(engine, 'single_instance_lock'), patch.object(engine.uvicorn, 'Server') as server, patch.object(engine, 'set_state') as write:
            server.return_value.run.side_effect = KeyboardInterrupt
            engine.main()
            write.assert_called_once_with('STOPPED', 'Owner interrupted engine; explicit start required', expected='RUNNING')
