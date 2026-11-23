# Changelog

All notable changes to the Responsible Technology Examination and Credential Platform demonstrator.

## [2.0.0] - Day-4 Redesign

### Changed
- **Suggestions Turned Off for Software Engineering**:
  - Analysis of examiner reference data revealed severe label inconsistency and noise in Software Engineering answers (historical vs. expert quadratic weighted kappa of 0.50 vs. 0.88 for OS and 0.86 for DBMS).
  - To mitigate automation bias and unwarranted anchoring on subjective questions, automated rubric suggestions are turned off for the Software Engineering subject; scripts in this subject remain strictly under human double-blind evaluation.
- **Signed Digital Credentials Replace Blockchain Ledger**:
  - Replaced the distributed ledger / blockchain component (Alternative C) with asymmetric Ed25519 digital credential signing (`src/credentials.py`).
  - Achieves instant offline verifiability, tamper resistance, and revocation support without ledger consensus delay, node infrastructure overhead, or volatile transaction gas fees.
- **Privacy-Compliant Audit Redaction Service**:
  - Added a privacy redaction mechanism (`redact_payload` in `src/store.py`, verified in Scenario V11) to comply with data protection regulations (GDPR / DPDP Act).
  - Enables redacting sensitive student responses and identifying details while maintaining the integrity of the SHA-256 audit hash chain.
- **Halved Computing Budget Adaptation**:
  - Adapted the platform cost model for a 50% cut in annual compute budget (from Rs. 3.0 lakh to Rs. 1.5 lakh per year).
  - The revised architecture (Alternative A-revised) requires only Rs. 0.35 lakh/year in infrastructure, fitting comfortably within the reduced limit, whereas heavy ML and blockchain alternatives exceed both the original and revised budgets.
