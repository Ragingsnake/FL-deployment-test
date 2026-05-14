#!/usr/bin/env bash
# Patches hardcoded localhost endpoints in the upstream repo so the code
# becomes container/cluster friendly. Idempotent.
set -euo pipefail
WORKDIR="${1:-.}"
cd "$WORKDIR"

python3 - <<'PY'
import os, re, pathlib
root = pathlib.Path(".")

def patch(path, pairs):
    p = root / path
    if not p.exists(): return
    s = p.read_text()
    orig = s
    for pat, rep in pairs:
        s = re.sub(pat, rep, s)
    if s != orig:
        p.write_text(s)
        print(f"patched {path}")

# blockchain.py — use env for RPC + dynamic contract address
patch("blockchain.py", [
    (r'Web3\.HTTPProvider\("http://127\.0\.0\.1:7545"\)',
     'Web3.HTTPProvider(os.environ.get("ETH_RPC","http://127.0.0.1:7545"))'),
    (r'contract_address\s*=\s*"0x[0-9a-fA-F]{40}"',
     'contract_address = os.environ.get("REPUTATION_ADDRESS") or '
     '(open(os.environ.get("CONTRACT_ADDRESS_FILE","/app/build/contracts/Reputation.address")).read().strip() '
     'if os.path.exists(os.environ.get("CONTRACT_ADDRESS_FILE","/app/build/contracts/Reputation.address")) else None)'),
])
# add `import os` if missing
p = root / "blockchain.py"
if p.exists():
    s = p.read_text()
    if "import os" not in s.splitlines()[0:5]:
        s = "import os\n" + s

    # Clique/PoA chains require middleware for 97-byte extraData fields.
    if "middleware_onion.inject" not in s and "w3 = Web3(" in s:
        s = re.sub(
            r'(w3\s*=\s*Web3\([^\n]+\)\n)',
            r'\1try:\n'
            r'    from web3.middleware import ExtraDataToPOAMiddleware\n'
            r'    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)\n'
            r'except Exception:\n'
            r'    try:\n'
            r'        from web3.middleware import geth_poa_middleware\n'
            r'        w3.middleware_onion.inject(geth_poa_middleware, layer=0)\n'
            r'    except Exception:\n'
            r'        pass\n',
            s,
            count=1,
        )

    p.write_text(s)

# ipfs_utils.py — env-driven multiaddr
patch("ipfs_utils.py", [
    (r'ipfshttpclient\.connect\("/ip4/127\.0\.0\.1/tcp/5001"\)',
     'ipfshttpclient.connect(os.environ.get("IPFS_API","/ip4/127.0.0.1/tcp/5001"))'),
])
p = root / "ipfs_utils.py"
if p.exists():
    s = p.read_text()
    if "import os" not in s:
        p.write_text("import os\n" + s)

# fl_client.py — env-driven server address
patch("fl_client.py", [
    (r'server_address="localhost:8080"',
     'server_address=f"{os.environ.get(\'FL_SERVER_HOST\',\'localhost\')}:{os.environ.get(\'FL_SERVER_PORT\',\'8080\')}"'),
])
p = root / "fl_client.py"
if p.exists():
    s = p.read_text()
    if "import os" not in s:
        # insert after the first import line
        lines = s.splitlines()
        lines.insert(0, "import os")
        p.write_text("\n".join(lines))

# truffle-config.js — add a "kube" network pointing at the geth service
tc = root / "truffle-config.js"
if tc.exists() and "kube:" not in tc.read_text():
    src = tc.read_text()
    inject = """
    kube: {
      host: process.env.GETH_HOST || "geth-svc",
      port: 8545,
      network_id: "1337",
      from: undefined,
      gas: 6000000
    },
"""
    src = re.sub(r"networks:\s*\{", "networks: {" + inject, src, count=1)
    tc.write_text(src)
    print("patched truffle-config.js")
PY

echo "Fixes applied."
