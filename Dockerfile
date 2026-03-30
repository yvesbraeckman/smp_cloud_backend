# Gebruik een lichte, officiële Python versie
FROM python:3.11-slim

# Zet de werkmap in de container
WORKDIR /app

# Kopieer de requirements en installeer ze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer de rest van je code naar de container
COPY . .

# Start de FastAPI server via Uvicorn op poort 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
