import sys

from auth import AuthSession
from control_client import ControlClient
from datanode_client import DataNodeClient
from transfer import FileTransfer

USAGE = (
    "usage: client.py login | ls [PATH] | mkdir PATH | rm PATH | rmdir PATH | "
    "put SOURCE REMOTE_PATH | get REMOTE_PATH DESTINATION | "
    "open REMOTE_PATH [r|w|a] | close SESSION_ID | read SESSION_ID OFFSET LENGTH DESTINATION | "
    "lock SESSION_ID | unlock SESSION_ID"
)

#Coordina la ejecución de comandos del cliente DFS, manejando la autenticación, las operaciones de control y la transferencia de archivos entre el cliente y los nodos de datos.

def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(USAGE)

    auth = AuthSession()
    auth.login()
    control = ControlClient(auth)
    transfer = FileTransfer(control, DataNodeClient())
    command = sys.argv[1]

    if command == "login":
        pass
    elif command == "ls":
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
