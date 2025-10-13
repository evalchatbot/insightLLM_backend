from __future__ import annotations
import os, uuid, datetime
from typing import Optional
from supabase import create_client, Client

class StorageService:
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")
        self.client: Client = create_client(url, key)
        self.bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "annotated_pdfs")
        self.ttl = int(os.getenv("SIGNED_URL_TTL_SECONDS", "3600"))

    def upload_pdf_and_get_signed_url(self, *, user_id: str, original_stem: str, data: bytes) -> str:
        today = datetime.datetime.utcnow()
        path = f"annotated/{user_id}/{today:%Y/%m/%d}/{uuid.uuid4()}_{original_stem}.pdf"
        # upload (private bucket is fine; service role bypasses RLS)
        self.client.storage.from_(self.bucket).upload(path=path, file=data, file_options={"content-type": "application/pdf", "upsert": False})
        signed = self.client.storage.from_(self.bucket).create_signed_url(path, self.ttl)
        return signed.get("signedURL") or signed.get("signed_url") or ""