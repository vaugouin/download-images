#!/bin/bash

# Check if the tmdb-export Docker container is running
if [ $(docker ps -q -f name=tmdb-export) ]; then
    echo "tmdb-export Docker container is already running."
else
    # Start the tmdb-export container if it is not running
    cd /home/debian/docker/download-images
    mkdir -p "/home/debian/docker/download-images/logs"
    docker build -t tmdb-export-python-app .
    docker run -d --rm --network="host" --env-file /home/debian/docker/download-images/.env -v "/home/debian/docker/download-images/csv:/csv" --name tmdb-export tmdb-export-python-app
    echo "tmdb-export Docker container started."
fi
