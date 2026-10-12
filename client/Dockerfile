FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dfsha.proto cli.py config.py auth.py control_client.py datanode_client.py transfer.py tls.py ./
RUN pip install --no-cache-dir grpcio-tools==1.69.0 && python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. dfsha.proto
ENTRYPOINT ["python", "cli.py"]
