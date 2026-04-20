from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
PARSED_DIR = STORAGE_DIR / "parsed"
EXPORT_DIR = STORAGE_DIR / "exports"
DB_PATH = STORAGE_DIR / "corpus.db"
ASSETS_DIR = BASE_DIR / "assets"

