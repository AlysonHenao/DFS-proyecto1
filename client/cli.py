import json
import os
from pathlib import Path
import sys
import requests

from auth import AuthSession
from config import session_file
from control_client import ControlClient
from datanode_client import DataNodeClient
from transfer import FileTransfer

USAGE = (
    "usage: client.py register [USERNAME] [PASSWORD] | login [USERNAME] [PASSWORD] | ls [PATH] | "
    "mkdir PATH | rm PATH | rmdir PATH | "
    "put SOURCE REMOTE_PATH | get REMOTE_PATH DESTINATION | "
    "open REMOTE_PATH [r|w|a] | close SESSION_ID | read SESSION_ID OFFSET LENGTH DESTINATION | "
    "write SESSION_ID OFFSET DATA | write_plan SESSION_ID OFFSET LENGTH | lock SESSION_ID | unlock SESSION_ID"
)


def _pending_blocks_path() -> Path:
    return Path(session_file()).parent / ".dfsha-rf3-blocks.json"


def _load_pending_blocks(session_id: str) -> list[dict] | None:
    p = _pending_blocks_path()
    if not p.is_file():
        return None
    try:
        store = json.loads(p.read_text(encoding="utf-8"))
        return store.get(session_id)
    except Exception:
        return None


def _save_pending_blocks(session_id: str, blocks: list[dict]) -> None:
    p = _pending_blocks_path()
    try:
        store = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        store = {}
    existing = store.get(session_id, [])
    by_idx = {b["index"]: b for b in existing}
    for b in blocks:
        by_idx[b["index"]] = b
    store[session_id] = [by_idx[k] for k in sorted(by_idx.keys())]
    p.write_text(json.dumps(store), encoding="utf-8")


def _clear_pending_blocks(session_id: str) -> None:
    p = _pending_blocks_path()
    if not p.is_file():
        return
    try:
        store = json.loads(p.read_text(encoding="utf-8"))
        store.pop(session_id, None)
        p.write_text(json.dumps(store), encoding="utf-8")
    except Exception:
        pass


# Coordina la ejecución de comandos del cliente DFS, manejando la autenticación, las operaciones de control y la transferencia de archivos entre el cliente y los nodos de datos.

def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(USAGE)

    command = sys.argv[1]

    auth = AuthSession()
    control = ControlClient(auth)

    if command == "register" and len(sys.argv) in (2, 3, 4):
        username = sys.argv[2] if len(sys.argv) >= 3 else None
        password = sys.argv[3] if len(sys.argv) == 4 else None
        username, password = auth.credentials(username, password, confirm=(password is None and not os.getenv("DFSHA_PASSWORD")))
        result = control.register(username, password)
        print(f"registered: {result['username']}")
        return
    if command == "login" and len(sys.argv) in (2, 3, 4):
        username = sys.argv[2] if len(sys.argv) >= 3 else None
        password = sys.argv[3] if len(sys.argv) == 4 else None
        auth.login(username, password)
        print("login ok")
        return

    if not auth.load():
        auth.login()
    transfer = FileTransfer(control, DataNodeClient())
    if command == "ls":
        path = sys.argv[2] if len(sys.argv) == 3 else "/"
        for entry in control.ls(path):
            print(f"{entry['type']}\t{entry['size']}\t{entry['name']}")
    elif command == "mkdir" and len(sys.argv) == 3:
        control.mkdir(sys.argv[2])
    elif command == "rm" and len(sys.argv) == 3:
        control.remove_file(sys.argv[2])
    elif command == "rmdir" and len(sys.argv) == 3:
        control.remove_directory(sys.argv[2])
    elif command == "put" and len(sys.argv) == 4:
        transfer.upload(sys.argv[2], sys.argv[3])
    elif command == "get" and len(sys.argv) == 4:
        transfer.download(sys.argv[2], sys.argv[3])
    elif command == "open" and len(sys.argv) in (3, 4):
        mode = sys.argv[3] if len(sys.argv) == 4 else "r"
        if mode not in {"r", "w", "a"}:
            raise SystemExit(USAGE)
        session = control.open_file(sys.argv[2], mode, mode == "a")
        print(session["session_id"])
    elif command == "close" and len(sys.argv) == 3:
        sid = sys.argv[2]
        pending = _load_pending_blocks(sid)
        res = control.close_file(sid, pending)
        _clear_pending_blocks(sid)
        if "version" in res:
            print(f"version: {res['version']}")
    elif command == "write" and len(sys.argv) == 5:
        # sys.argv[2]=session_id, sys.argv[3]=offset, sys.argv[4]=data
        session_id = sys.argv[2]
        offset = int(sys.argv[3])
        raw_bytes = sys.argv[4].encode("utf-8")
        plan = control.plan_write(session_id, offset, len(raw_bytes))
        written = []
        cursor = 0
        for blk in plan["blocks"]:
            chunk = raw_bytes[cursor:cursor + blk["size"]]
            cursor += len(chunk)
            info = transfer.write_block_copy(blk, chunk)
            info["size"] = len(chunk)
            written.append(info)
        _save_pending_blocks(session_id, written)
    elif command == "write_plan" and len(sys.argv) == 5:
        # sys.argv[2]=session_id, sys.argv[3]=offset, sys.argv[4]=length
        session_id = sys.argv[2]
        offset = int(sys.argv[3])
        length = int(sys.argv[4])
        plan = control.plan_write(session_id, offset, length, append=False)
        import json
        json.dump(plan, sys.stdout, indent=2)
        print()
    elif command == "lock" and len(sys.argv) == 3:
        control.lock_file(sys.argv[2])
    elif command == "unlock" and len(sys.argv) == 3:
        control.unlock_file(sys.argv[2])
    elif command == "read" and len(sys.argv) == 6:
        session_id, offset, length, destination = (
            sys.argv[2],
            int(sys.argv[3]),
            int(sys.argv[4]),
            sys.argv[5],
        )
        plan = control.plan_read(session_id, offset, length)
        with open(destination, "wb") as output:
            output.write(transfer.read_range(plan, offset, length))
    else:
        raise SystemExit(USAGE)
    print("ok")


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.HTTPError as err:
        status = err.response.status_code if err.response is not None else "?"
        detail = err.response.text if err.response is not None else str(err)
        print(f"HTTP {status}: {detail}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as err:
        print(f"Error: {err}", file=sys.stderr)
        raise SystemExit(1)
