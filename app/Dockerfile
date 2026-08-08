FROM python:3.13-slim-bookworm

WORKDIR /usr/src/app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt

COPY entrypoint.sh ./
RUN sed -i 's/\r$//g' entrypoint.sh && chmod +x entrypoint.sh
COPY . .

ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
