#!/bin/bash

/opt/graphdb/dist/bin/graphdb &
GRAPHDB_PID=$!

echo 'Waiting for GraphDB to be ready...'
until curl -sf http://localhost:7200/rest/repositories > /dev/null 2>&1; do
    sleep 5
done
echo 'GraphDB is ready'

if (cd /app && python3 code/etl.py); then
    echo 'ETL complete. GraphDB is serving traffic...'
else
    echo 'ETL failed - see the errors above. GraphDB is still serving traffic...'
fi
wait $GRAPHDB_PID
