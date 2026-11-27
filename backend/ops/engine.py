"""One owned engine; graceful state transitions with no shell window."""
import threading
import uvicorn
from ops.control import read_state, set_state
from ops.watchdog import single_instance_lock


def main():
    lock = single_instance_lock(8800)
    if lock is None:
        return
    try:
        while read_state()['state'] in ('RUNNING', 'PAUSED'):
            mode = read_state()['state']
            server = uvicorn.Server(uvicorn.Config('main:app', host='127.0.0.1', port=8000))
            done = threading.Event()

            def monitor():
                while not done.wait(1):
                    if read_state()['state'] != mode:
                        server.should_exit = True
                        return
            thread = threading.Thread(target=monitor, daemon=True)
            thread.start()
            try:
                server.run()
            except KeyboardInterrupt:
                set_state('STOPPED', 'Owner interrupted engine; explicit start required', expected=mode)
                return
            finally:
                done.set()
                thread.join(timeout=2)
            if read_state()['state'] == mode:
                set_state('STOPPED', 'Engine exited normally; explicit start required', expected=mode)
    finally:
        lock.close()


if __name__ == '__main__':
    main()
