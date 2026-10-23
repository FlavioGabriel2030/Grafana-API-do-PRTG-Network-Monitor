FROM python:3.12-slim
RUN useradd --system --uid 10001 topo
WORKDIR /app
COPY servidor.py index.html mosaico.html fluxo.html config.json ./
USER topo
ENV TOPO_BIND=0.0.0.0 TOPO_PORTA=8090 PYTHONUNBUFFERED=1
EXPOSE 8090
HEALTHCHECK --interval=60s --timeout=5s --start-period=90s \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/saude', timeout=4).status == 200 else 1)"
CMD ["python", "servidor.py"]
