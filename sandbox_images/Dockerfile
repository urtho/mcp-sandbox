FROM quay.io/jupyter/scipy-notebook:latest

# scipy-notebook ships numpy, pandas, matplotlib, scipy, scikit-learn, seaborn,
# sympy, statsmodels, bokeh, dask, numba, scikit-image, sqlalchemy, etc.
# See https://jupyter-docker-stacks.readthedocs.io/

USER root
RUN mkdir -p /app/results \
    && chown -R ${NB_UID}:${NB_GID} /app \
    && apt-get update \
    && apt-get install -y --no-install-recommends coreutils \
    && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# uv is the package manager the MCP tools use at runtime.
RUN pip install --no-cache-dir uv

# tmpfs is remounted over /app/results at container create time; keeping this
# as the default workdir is still the simplest convention for our tool code.
WORKDIR /app/results

CMD ["sleep", "infinity"]
