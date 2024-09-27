FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1
ENV POETRY_VERSION="1.4.0"
ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV VENV_HOME=/opt/poetry
WORKDIR /app

#RUN apt-get update \
#&& apt-get -y upgrade \
#&& apt-get -y install \
#        git \
#        gcc \
#        python3-levenshtein

COPY poetry.lock pyproject.toml ./
RUN apt-get update \
 && apt-get -y install python3-pip \
 && apt-get clean && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv ${VENV_HOME} \
 && ${VENV_HOME}/bin/pip install --upgrade pip \
 && ${VENV_HOME}/bin/pip install "poetry==${POETRY_VERSION}" \
 && ${VENV_HOME}/bin/poetry check \
 && POETRY_VIRTUALENVS_CREATE=false ${VENV_HOME}/bin/poetry install --no-interaction --no-cache --only main \
 && ${VENV_HOME}/bin/pip uninstall -y poetry

# Add Poetry to PATH
ENV PATH="${VENV_HOME}/bin:${PATH}"

COPY keel_telegram_bot keel_telegram_bot
COPY README.md README.md

RUN ${VENV_HOME}/bin/pip install .

ENTRYPOINT [ "keel-telegram-bot" ]
