# The privileged snapshot helper (Mf-o6si). It runs as root with CAP_SYS_ADMIN by
# design -- btrfs cannot snapshot without it -- which is why every containment
# rule in guard.py exists: one bind-mounted subvolume, a name the guard validates
# and re-contains, argv-only btrfs commands, no shell, and no published port.
FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends btrfs-progs \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY guard.py server.py ./
ENV SNAPSHOT_BTRFS_SIDECAR_MOUNT=/library
EXPOSE 8765
CMD ["python", "server.py"]
