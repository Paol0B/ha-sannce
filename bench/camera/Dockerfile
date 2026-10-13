FROM python:3.14.4-slim
ENV PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir aiohttp==3.14.4
COPY lib /src/lib
RUN pip install --no-cache-dir --no-deps /src/lib
USER nobody
ENTRYPOINT ["python", "-m", "sannce_aio", "simulate"]
