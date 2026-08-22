#!/bin/sh
set -eu

umask 077

mkdir -p /data /music /run/novin

for directory in /data /music /run/novin; do
    if [ ! -w "$directory" ]; then
        echo "required writable directory is unavailable: $directory" >&2
        exit 1
    fi
done

exec "$@"
