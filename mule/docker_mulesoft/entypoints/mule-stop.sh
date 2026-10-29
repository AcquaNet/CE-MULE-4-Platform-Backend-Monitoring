#!/bin/bash
echo "Stopping Mule $(cat /opt/mule/mule-version.txt) (image built $(cat /opt/mule/build-date.txt))" >/home/stop.log
exec "$MULE_HOME/bin/mule" stop
