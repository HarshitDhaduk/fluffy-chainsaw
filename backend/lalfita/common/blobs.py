"""Document vault storage abstraction.

InMemoryBlobStore — local dev/tests (mem:// URIs).
GcsBlobStore — cloud: Cloud Storage under gs://<bucket>/journeys/…, which is
the 'document vault' shown to judges. Access from services goes through
signed service accounts; nothing is public."""

import asyncio


class BlobStore:
    async def put(
        self, journey_id: str, doc_id: str, filename: str, content: bytes, content_type: str
    ) -> str:
        raise NotImplementedError

    async def get(self, uri: str) -> bytes:
        raise NotImplementedError


class InMemoryBlobStore(BlobStore):
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def put(self, journey_id, doc_id, filename, content, content_type) -> str:
        uri = f"mem://{journey_id}/{doc_id}/{filename}"
        self._data[uri] = content
        return uri

    async def get(self, uri: str) -> bytes:
        return self._data[uri]


class GcsBlobStore(BlobStore):
    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket_name)
        self._bucket_name = bucket_name

    async def put(self, journey_id, doc_id, filename, content, content_type) -> str:
        path = f"journeys/{journey_id}/{doc_id}/{filename}"
        blob = self._bucket.blob(path)
        await asyncio.to_thread(blob.upload_from_string, content, content_type=content_type)
        return f"gs://{self._bucket_name}/{path}"

    async def get(self, uri: str) -> bytes:
        path = uri.removeprefix(f"gs://{self._bucket_name}/")
        blob = self._bucket.blob(path)
        return await asyncio.to_thread(blob.download_as_bytes)
