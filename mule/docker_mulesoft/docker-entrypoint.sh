#!/bin/bash
DIR=/docker-entrypoint.d   
cd /docker-entrypoint.d
./mule-start.sh
exec "$@"