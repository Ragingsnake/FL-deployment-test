import os
# ipfs_utils.py

import ipfshttpclient


def upload_to_ipfs(file_path):

    try:

        client = ipfshttpclient.connect(os.environ.get("IPFS_API","/ip4/127.0.0.1/tcp/5001"))

        res = client.add(file_path)

        cid = res["Hash"]

        print(f"📦 Uploaded {file_path} -> CID: {cid}")

        return cid

    except Exception as e:

        print("❌ IPFS Upload Failed:", e)

        return "IPFS_ERROR"