#!/bin/bash

# Check if the tmdb-export Docker container is running
if [ $(docker ps -q -f name=tmdb-export) ]; then
    echo "tmdb-export Docker container is already running."
else
    # Start the tmdb-export container if it is not running
    cd $HOME/docker/download-images
    docker build -t tmdb-export-python-app .
    docker run -d --rm --network="host" --env-file .env -v "$(pwd)/csv:/csv" --name tmdb-export tmdb-export-python-app
    mkdir -p "$HOME/docker/download-images/logs"
    nohup docker logs -f tmdb-export \
        > "$HOME/docker/download-images/logs/export-$(date +%F).log" 2>&1 &
    disown
    echo "tmdb-export Docker container started."
fi
