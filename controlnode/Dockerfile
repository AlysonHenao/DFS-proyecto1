FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dfsha.proto schema.sql ./
COPY models ./models
COPY __init__.py config.py db.py auth.py grpc_server.py monitor.py app.py ./
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. dfsha.proto
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
