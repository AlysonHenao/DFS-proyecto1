FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dfsha.proto app.py grpc_server.py ./
COPY models ./models
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. dfsha.proto
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
