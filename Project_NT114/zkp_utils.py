import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request


FIELD_MODULUS = 21888242871839275222246405745257275088548364400416034343698204186575808495617
ZK_VECTOR_SIZE = int(os.environ.get("ZK_VECTOR_SIZE", "128"))
ZK_SCALE = int(os.environ.get("ZK_SCALE", "100"))
ZK_NORM_BOUND = int(os.environ.get("ZK_NORM_BOUND", "60000"))

ZKEY_PATH = os.environ.get("ZKEY_PATH", "circuit_final.zkey")
WASM_PATH = os.environ.get("WASM_PATH", "prove_gradient_norm_js/prove_gradient_norm.wasm")
VK_PATH = os.environ.get("VK_PATH", "verification_key.json")
WITNESS_JS = os.environ.get("WITNESS_JS", "prove_gradient_norm_js/generate_witness.js")
ZKP_NODE_URL = os.environ.get("ZKP_NODE_URL", "").rstrip("/")
ZKP_LOCAL_ONLY = os.environ.get("ZKP_LOCAL_ONLY", "0") == "1"
ZKP_NODE_TIMEOUT = int(os.environ.get("ZKP_NODE_TIMEOUT", "300"))


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def canonical_proof_json(proof):
    return canonical_json(proof)


def proof_hash(proof):
    return hashlib.sha256(canonical_proof_json(proof).encode("utf-8")).hexdigest()


def hash_model(parameters):
    digest = hashlib.sha256()
    for p in parameters:
        digest.update(str(p.dtype).encode("utf-8"))
        digest.update(str(p.shape).encode("utf-8"))
        digest.update(p.tobytes())
    return int(digest.hexdigest(), 16) % FIELD_MODULUS


def _public_signals(parameters, client_id, round_num, norm_bound=None):
    return [
        str(hash_model(parameters)),
        str(int(client_id)),
        str(int(round_num)),
        str(int(norm_bound if norm_bound is not None else ZK_NORM_BOUND)),
    ]


def _gradient_witness(parameters):
    values = []
    for layer in parameters:
        values.extend(layer.flatten())

    gradient = [abs(int(round(float(x) * ZK_SCALE))) for x in values[:ZK_VECTOR_SIZE]]
    while len(gradient) < ZK_VECTOR_SIZE:
        gradient.append(0)
    return gradient


def build_input(parameters, client_id, round_num, norm_bound=None):
    bound = int(norm_bound if norm_bound is not None else ZK_NORM_BOUND)
    return {
        "gradient": _gradient_witness(parameters),
        "model_hash": int(hash_model(parameters)),
        "client_id": int(client_id),
        "round_num": int(round_num),
        "norm_bound": bound,
    }


def _node_post(path, payload):
    if not ZKP_NODE_URL:
        raise RuntimeError("ZKP_NODE_URL is not configured")

    request = urllib.request.Request(
        f"{ZKP_NODE_URL}{path}",
        data=canonical_json(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=ZKP_NODE_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ZKP node {path} failed: HTTP {exc.code}: {body}") from exc


def _local_generate(input_json):
    with tempfile.TemporaryDirectory() as tmp:
        inp = os.path.join(tmp, "input.json")
        wit = os.path.join(tmp, "witness.wtns")
        prf = os.path.join(tmp, "proof.json")
        pub = os.path.join(tmp, "public.json")

        with open(inp, "w", encoding="utf-8") as f:
            json.dump(input_json, f)

        subprocess.run(["node", WITNESS_JS, WASM_PATH, inp, wit], check=True)
        subprocess.run(["snarkjs", "groth16", "prove", ZKEY_PATH, wit, prf, pub], check=True)

        with open(prf, "r", encoding="utf-8") as f:
            proof = json.load(f)
        with open(pub, "r", encoding="utf-8") as f:
            public = json.load(f)

    return {"proof": proof, "public": [str(x) for x in public]}


def _local_verify(proof_data):
    with tempfile.TemporaryDirectory() as tmp:
        prf = os.path.join(tmp, "proof.json")
        pub = os.path.join(tmp, "public.json")

        with open(prf, "w", encoding="utf-8") as f:
            json.dump(proof_data["proof"], f)
        with open(pub, "w", encoding="utf-8") as f:
            json.dump(proof_data["public"], f)

        result = subprocess.run(
            ["snarkjs", "groth16", "verify", VK_PATH, pub, prf],
            capture_output=True,
            text=True,
            check=False,
        )

    return result.returncode == 0 and "OK" in result.stdout


def generate_proof(parameters, client_id=None, round_num=None, cid=None, norm_bound=None):
    input_json = build_input(parameters, client_id, round_num, norm_bound)

    if ZKP_NODE_URL and not ZKP_LOCAL_ONLY:
        result = _node_post("/prove", {"input": input_json})
        proof_data = result.get("proof_data")
        if not proof_data:
            raise RuntimeError(f"ZKP node returned no proof_data: {result}")
    else:
        proof_data = _local_generate(input_json)

    expected_public = [
        str(input_json["model_hash"]),
        str(input_json["client_id"]),
        str(input_json["round_num"]),
        str(input_json["norm_bound"]),
    ]
    if [str(x) for x in proof_data.get("public", [])] != expected_public:
        raise RuntimeError("Generated zkSNARK public signals do not match the submitted update")

    proof_data["backend"] = "groth16"
    return proof_data


def verify_proof(parameters, proof_data, client_id=None, round_num=None, cid=None, norm_bound=None):
    if not isinstance(proof_data, dict):
        return False
    if "proof" not in proof_data or "public" not in proof_data:
        return False

    expected_public = _public_signals(parameters, client_id, round_num, norm_bound)
    if [str(x) for x in proof_data.get("public", [])] != expected_public:
        return False

    if ZKP_NODE_URL and not ZKP_LOCAL_ONLY:
        result = _node_post("/verify", {"proof_data": proof_data})
        return bool(result.get("valid"))

    return _local_verify(proof_data)
