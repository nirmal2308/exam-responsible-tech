"""Signed degree-credential records (replacement for a shared ledger).

An Ed25519 signature by the university lets ANY verifier check, offline, that a
credential record was issued unchanged. A signed revocation list supports correction.
LIMITATION: a signature proves who issued the record and that it is unchanged; it does
NOT prove that the underlying marks or the degree award were correct.
"""
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Issuer:
    def __init__(self):
        self._sk = Ed25519PrivateKey.generate()
        self.public_key = self._sk.public_key()
        self.revoked = []
        self.rev_version = 0

    def issue(self, cred_id, student_pseudonym, degree, year, cgpa_band):
        claims = {"cred_id": cred_id, "subject": student_pseudonym, "degree": degree,
                  "year": year, "band": cgpa_band, "issuer": "SIMATS-demo"}
        return {"claims": claims, "sig": self._sk.sign(canon(claims)).hex()}

    def revoke(self, cred_id):
        self.revoked.append(cred_id); self.rev_version += 1

    def revocation_list(self):
        body = {"version": self.rev_version, "revoked": sorted(self.revoked)}
        return {"body": body, "sig": self._sk.sign(canon(body)).hex()}


def verify(cred, public_key, rev_list=None):
    """Returns (valid, reason). Works offline: needs only the public key (+ cached revocation list)."""
    try:
        public_key.verify(bytes.fromhex(cred["sig"]), canon(cred["claims"]))
    except (InvalidSignature, ValueError, KeyError):
        return False, "signature invalid or record altered"
    if rev_list is not None:
        try:
            public_key.verify(bytes.fromhex(rev_list["sig"]), canon(rev_list["body"]))
        except (InvalidSignature, ValueError, KeyError):
            return False, "revocation list signature invalid"
        if cred["claims"]["cred_id"] in rev_list["body"]["revoked"]:
            return False, "credential revoked (corrected or withdrawn)"
    return True, "valid: issued by university, unchanged"
