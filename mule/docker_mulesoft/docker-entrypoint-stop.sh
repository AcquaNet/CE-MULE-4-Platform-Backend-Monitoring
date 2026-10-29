#!/bin/bash
DIR=/docker-entrypoint.d   
cd /docker-entrypoint.d
./mule-stop.sh
exec "$@"