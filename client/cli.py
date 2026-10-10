import sys

from auth import AuthSession
from control_client import ControlClient
from datanode_client import DataNodeClient
from transfer import FileTransfer

USAGE = (
    "usage: client.py login | ls [PATH] | mkdir PATH | rm PATH | rmdir PATH | "
    "put SOURCE REMOTE_PATH | get REMOTE_PATH DESTINATION"
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
    else:
        raise SystemExit(USAGE)
    print("ok")


if __name__ == "__main__":
    main()
