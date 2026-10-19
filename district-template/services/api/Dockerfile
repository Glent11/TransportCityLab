FROM python:3.12-slim

# Непривилегированный пользователь (урок ЛР0): процесс в контейнере — не root
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY app.py .

USER appuser
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"
CMD ["python", "-u", "app.py"]
