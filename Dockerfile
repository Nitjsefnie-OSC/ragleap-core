FROM python:3.11-slim

WORKDIR /app

ENV PYTHONIOENCODING=UTF-8
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

COPY requirements.txt requirements.lock ./
# requirements.lock pins every package to the exact version that was tested; requirements.txt is the list people edit
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

# Run as an unprivileged user. The app writes no files of its own; HOME exists for libraries that cache there.
RUN useradd --system --uid 10001 --create-home --home-dir /home/ragleap --shell /usr/sbin/nologin ragleap
ENV HOME=/home/ragleap PYTHONDONTWRITEBYTECODE=1
USER ragleap

EXPOSE 8000

CMD ["uvicorn", "core.api:app", "--host", "0.0.0.0", "--port", "8000"]
