FROM python:3.14.4-slim
RUN pip install --no-cache-dir aiohttp==3.14.4
COPY lib /src/lib
RUN pip install --no-cache-dir --no-deps /src/lib
USER nobody
ENTRYPOINT ["python", "-m", "sannce_aio", "simulate"]
