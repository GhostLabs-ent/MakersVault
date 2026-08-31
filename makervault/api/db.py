import os
from pathlib import Path
from sqlmodel import create_engine

from content_store import ContentStore, LocalContentStore

DB_URL = os.getenv("DB_URL", "sqlite:///./app.db")
LOCAL_CONTENT_STORE = LocalContentStore(Path(os.getenv("FILE_STORAGE", "./storage")))
CONTENT_STORE: ContentStore = LOCAL_CONTENT_STORE
# Compatibility paths remain for callers and tests that legitimately require a
# local materialized path. Authoritative services consume CONTENT_STORE directly.
STORAGE = LOCAL_CONTENT_STORE.root
THUMBS = LOCAL_CONTENT_STORE.local_path("thumbs")
THUMBS.mkdir(parents=True, exist_ok=True)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
