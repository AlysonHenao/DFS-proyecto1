import os
import sys

from auth import AuthSession
from control_client import ControlClient
from datanode_client import DataNodeClient
from transfer import FileTransfer

USAGE = (
    "usage: client.py register [USERNAME] [PASSWORD] | login [USERNAME] [PASSWORD] | ls [PATH] | "
    "mkdir PATH | rm PATH | rmdir PATH | "
    "put SOURCE REMOTE_PATH | get REMOTE_PATH DESTINATION | "
    "open REMOTE_PATH [r|w|a] | close SESSION_ID | read SESSION_ID OFFSET LENGTH DESTINATION | "
    "lock SESSION_ID | unlock SESSION_ID"
)

#Coordina la ejecución de comandos del cliente DFS, manejando la autenticación, las operaciones de control y la transferencia de archivos entre el cliente y los nodos de datos.

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
        control.close_file(sys.argv[2])
    elif command == "write" and len(sys.argv) == 5:
        # sys.argv[2]=session_id, sys.argv[3]=offset, sys.argv[4]=data
        session_id = sys.argv[2]
        offset = int(sys.argv[3])
        data = sys.argv[4]
        control.write_file(session_id, offset, data)
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
    main()
