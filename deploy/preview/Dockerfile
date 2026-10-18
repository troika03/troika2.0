ARG NODE_IMAGE=node@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5
ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright/python@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0
FROM ${NODE_IMAGE} AS node
FROM ${PLAYWRIGHT_IMAGE}
USER root
RUN test "$(id -u pwuser)" = 1001
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer libreoffice-impress poppler-utils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir playwright==1.63.0 Pillow==11.3.0 pytest==8.4.2
COPY package.json package-lock.json /runner/
RUN cd /runner && npm ci --ignore-scripts --no-audit --no-fund
COPY build.mjs css_check.mjs vitest.config.mjs /runner/
COPY worker.py python_tests.py /runner/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
USER pwuser
WORKDIR /work
ENTRYPOINT []
CMD ["python", "/runner/worker.py"]
