#!/bin/sh

echo "Starting backend service..."

echo "Waiting for Redis to be ready..."
while ! nc -z redis 6379; do
    sleep 1
done
echo "Redis is ready!"

exec "$@"