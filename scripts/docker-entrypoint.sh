#!/bin/sh
set -e

if [ "${ENVIRONMENT}" = "production" ] && [ "${AUTH_API_KEY_PEPPER}" = "dev-insecure-pepper-change-me" ]; then
  echo "ERROR: AUTH_API_KEY_PEPPER must be set to a secure value in production" >&2
  exit 1
fi

if [ "${RUN_MIGRATIONS_ON_STARTUP:-true}" = "true" ]; then
  echo "Running Alembic migrations..."
  alembic upgrade head
fi

exec "$@"
