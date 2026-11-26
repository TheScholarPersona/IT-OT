FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples
RUN pip install --no-cache-dir . \
 && useradd --system --uid 10001 vplc \
 && mkdir -p /data && chown vplc /data

USER vplc
ENV VPLC_DATA=/data \
    VPLC_EXAMPLES=/app/examples \
    VPLC_PROTOCOL_HOST=0.0.0.0
VOLUME ["/data"]
# 8080 = Web/REST, 10102+ = S7comm, 4840+ = OPC UA (eine Portnummer je vPLC)
EXPOSE 8080 10102-10111 4840-4849
CMD ["vplc", "serve", "--host", "0.0.0.0", "--port", "8080", "--data", "/data"]
