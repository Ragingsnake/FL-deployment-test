import os
# ipfs_utils.py

import ipfshttpclient
import hashlib

_client = None


def _get_client():
    global _client

    if _client is None:
        _client = ipfshttpclient.connect(os.environ.get("IPFS_API","/ip4/127.0.0.1/tcp/5001"))

    return _client


def _fallback_cid(file_path):
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"local-{digest.hexdigest()}"


def upload_to_ipfs(file_path):

    try:

        client = _get_client()

        res = client.add(file_path)

        cid = res["Hash"]

        print(f"📦 Uploaded {file_path} -> CID: {cid}")

        return cid

    except Exception as e:

        print("❌ IPFS Upload Failed:", e)

        return _fallback_cid(file_path)