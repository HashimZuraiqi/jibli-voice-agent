"""Control the local careem-mcp server (spec/BUILD.md §6).

  python careem_mcp.py start | stop | status | logs
  python careem_mcp.py start --amman              groceries remember the cart (Jordanian catalog, JOD, Amman)
  python careem_mcp.py scenarios [tool]          list scenarios
  python careem_mcp.py scenario <tool> [name]    force a scenario (no name: clear it)
  python careem_mcp.py reset                      clear all forced scenarios
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

import server

RUN = server.HERE / ".run"
PID, LOG = RUN / "server.pid", RUN / "server.log"
PORT = int(os.getenv("CAREEM_MCP_PORT", "8787"))
URL = f"http://127.0.0.1:{PORT}"


def alive(pid):
    """Is the process running? On Windows os.kill(pid, 0) does not check, it TERMINATES the process (it killed the
    venv launcher and left the real server running with nothing able to stop it), so ask tasklist instead."""
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running_pid():
    try:
        pid = int(PID.read_text())
    except (OSError, ValueError):
        return None
    return pid if alive(pid) else None


def healthy():
    try:
        with urllib.request.urlopen(URL + "/health", timeout=2) as r:
            return json.loads(r.read())
    except OSError:
        return None


def start():
    if running_pid():
        print(f"already running on {URL}/mcp")
        return
    RUN.mkdir(exist_ok=True)
    env = dict(os.environ, **({"SANDBOX_WORLD": "amman"} if "--amman" in sys.argv else {}))
    proc = subprocess.Popen([sys.executable, str(server.HERE / "server.py"), "--port", str(PORT)], env=env,
                            stdout=open(LOG, "a"), stderr=subprocess.STDOUT, start_new_session=True)
    PID.write_text(str(proc.pid))
    for _ in range(50):
        if h := healthy():
            print(f"careem-mcp running: {URL}/mcp ({h['tools']} tools), logs: {LOG}")
            return
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    sys.exit(f"failed to start, see {LOG}")


def stop():
    pid = running_pid()
    if not pid:
        print("not running")
        return
    if os.name == "nt":  # /T: also the real interpreter the venv launcher started
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)
    PID.unlink(missing_ok=True)
    print("stopped")


def write_overrides(data):
    RUN.mkdir(exist_ok=True)
    server.OVERRIDES.write_text(json.dumps(data, indent=1), encoding="utf-8")


def main(argv):
    cmd = argv[0] if argv else "status"
    files = server.load_all() if cmd in ("scenarios", "scenario") else None
    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        h = healthy()
        print(f"running: {URL}/mcp, {h['tools']} tools" if h else "not running")
        print("forced scenarios:", server.overrides() or "none")
    elif cmd == "logs":
        print(LOG.read_text()[-5000:] if LOG.exists() else "no logs yet")
    elif cmd == "scenarios":
        for name in [argv[1]] if len(argv) > 1 else sorted(files):
            print(name + ": " + ", ".join(s["name"] for s in files[name]["scenarios"]))
    elif cmd == "scenario":
        tool = argv[1]
        if tool not in files:
            sys.exit(f"unknown tool {tool}")
        data = server.overrides()
        if len(argv) > 2:
            names = [s["name"] for s in files[tool]["scenarios"]]
            if argv[2] not in names:
                sys.exit(f"unknown scenario; {tool} has: {', '.join(names)}")
            data[tool] = argv[2]
        else:
            data.pop(tool, None)
        write_overrides(data)
        print("forced scenarios:", data or "none")
    elif cmd == "reset":
        write_overrides({})
        print("all scenarios back to normal")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
