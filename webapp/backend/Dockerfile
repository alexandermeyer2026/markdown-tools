FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r webapp/backend/requirements.txt

EXPOSE 8000

CMD ["uvicorn", "webapp.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
