FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer caches across script edits.
# Uses the export-only deps (no paramiko/httpx) to keep the image tight.
COPY requirements-export.txt ./
RUN pip install --no-cache-dir -r requirements-export.txt

# Only the export script ships in the image; download_images.py is Windows-side.
COPY export_image_tables.py ./

# CSVs are written here. Bind-mount this directory from the host.
# --out /csv is pinned in the ENTRYPOINT so a CSV_DIR coming from --env-file
# can never redirect output away from the bind mount. argparse honors the
# last --out, so users can still override with `docker run ... tmdb-export
# --out /elsewhere` if they really mean to.
VOLUME ["/csv"]

# -u keeps stdout unbuffered so progress bars stream in `docker logs`.
ENTRYPOINT ["python", "-u", "export_image_tables.py", "--out", "/csv"]
