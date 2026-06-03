import hashlib
import json
import secrets


# RFC 3526 2048-bit MODP Group. q=(p-1)/2 is prime, so Schnorr verification
# can run in the prime-order subgroup without external proving dependencies.
P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF",
    16,
)
Q = (P - 1) // 2
G = 2
PROOF_VERSION = "schnorr-nizk-v1"


def _sha256_bytes(*parts):
    m = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            m.update(part)
        else:
            m.update(str(part).encode("utf-8"))
    return m.digest()


def _challenge(statement, public_key, commitment):
    payload = json.dumps(
        {
            "version": PROOF_VERSION,
            "statement": statement,
            "public_key": str(public_key),
            "commitment": str(commitment),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return int.from_bytes(_sha256_bytes(payload), "big") % Q


def hash_model(parameters):
    m = hashlib.sha256()
    for p in parameters:
        m.update(str(p.dtype).encode("utf-8"))
        m.update(str(p.shape).encode("utf-8"))
        m.update(p.tobytes())
    return m.hexdigest()


def build_statement(parameters, client_id=None, round_num=None, cid=None):
    return {
        "model_hash": hash_model(parameters),
        "client_id": str(client_id) if client_id is not None else "",
        "round": int(round_num) if round_num is not None else 0,
        "cid": str(cid) if cid is not None else "",
    }


def canonical_proof_json(proof):
    return json.dumps(proof, sort_keys=True, separators=(",", ":"))


def proof_hash(proof):
    return hashlib.sha256(canonical_proof_json(proof).encode("utf-8")).hexdigest()


def generate_proof(parameters, client_id=None, round_num=None, cid=None):
    statement = build_statement(parameters, client_id, round_num, cid)

    secret = secrets.randbelow(Q - 1) + 1
    public_key = pow(G, secret, P)

    nonce = secrets.randbelow(Q - 1) + 1
    commitment = pow(G, nonce, P)
    challenge = _challenge(statement, public_key, commitment)
    response = (nonce + challenge * secret) % Q

    return {
        "version": PROOF_VERSION,
        "group": "rfc3526-2048-modp",
        "statement": statement,
        "public_key": str(public_key),
        "commitment": str(commitment),
        "response": str(response),
    }


def verify_proof(parameters, proof, client_id=None, round_num=None, cid=None):
    if not isinstance(proof, dict):
        return False

    try:
        if proof.get("version") != PROOF_VERSION:
            return False

        expected_statement = build_statement(parameters, client_id, round_num, cid)
        if proof.get("statement") != expected_statement:
            return False

        public_key = int(proof["public_key"])
        commitment = int(proof["commitment"])
        response = int(proof["response"])

        if not (1 < public_key < P - 1 and 1 < commitment < P - 1 and 0 <= response < Q):
            return False

        # Enforce subgroup membership to avoid small-subgroup tricks.
        if pow(public_key, Q, P) != 1 or pow(commitment, Q, P) != 1:
            return False

        challenge = _challenge(expected_statement, public_key, commitment)
        left = pow(G, response, P)
        right = (commitment * pow(public_key, challenge, P)) % P
        return left == right
    except (KeyError, TypeError, ValueError):
        return False
