# Fax Referral Triage Spec — v0.1

**Scope:** inbound *new referral* faxes to a specialty pharmacy intake queue, one form family
(the Accredo Prescription & Enrollment Form, 2 pages, four sections).
**Out of scope:** prior-authorization adjudication, benefit investigation, clinical criteria for
therapy approval, renewal/refill faxes (different form, different failure modes).

**Why fax persists:** the structured e-Rx message carries the prescription but not the enrollment
payload — insurance cards, ICD-10, clinical history, attestation. So the fax *is* the enrollment
application, and its defects are application defects, not transmission accidents.

---

## 0. Transport reality — what the fax layer can and cannot tell you

Three facts constrain everything downstream. They were checked against T.30 (ITU-T) and ITU-T T.4
Annex A (ECM), not assumed:

1. **The protocol carries no document length.** T.30's PPS signal has a *page count* byte, and it
   counts pages **sent**, modulo 256. Nothing anywhere in the protocol expresses how many pages the
   sender *intended* to send. A two-page referral arriving as one clean page is a perfectly valid,
   complete fax by protocol standards.
2. **"1 of 2" is a claim made by the sending machine at scan time**, derived from how many sheets
   physically passed through the ADF. It is exactly the metadata that fails when a page jams.
3. **In-call rejection cannot express "you forgot a page."** ECM (`PPR`) and non-ECM (`RTN`/`RTP`)
   let a receiver demand retransmission of a *damaged* page. There is no reason code for
   "incomplete document," and T.30 implementers note many senders mishandle RTN by treating it as
   RTP and continuing anyway.

**Consequence:** `D4_REJECT_REFAX` is a **workflow** action — quarantine the inbound into an
exception queue and request a re-send over a channel a human reads. It is not a fax-protocol
refusal. Refusing the call at the protocol layer only produces a generic TX error at the
prescriber's machine, which their staff cannot act on; they retry the same way and the defect
repeats. The re-request must arrive somewhere a person reads: phone, email, or the portal — using
the *office contact* captured in §2 of the form, which is therefore a blocking field.

---

## 1. Dispositions

Exactly one terminal disposition per fax. When multiple defects apply, the **highest severity wins**
and the others are recorded as secondary findings.

| ID | Disposition | Meaning | Owner | Target |
|----|-------------|---------|-------|--------|
| D0 | `AUTO_CLEAR` | All required fields present, valid, legible | system | immediate |
| D1 | `AUTO_REPAIR` | Defect resolvable from an attached artifact; repair **must cite the source** | system | immediate |
| D2 | `HUMAN_REVIEW` | Ambiguous but present; a person decides between bounded alternatives | intake pharmacist/tech | same shift |
| D3 | `PRESCRIBER_CALLBACK` | Only the prescriber can supply it | intake | 24h, escalate at 48h |
| D4 | `REJECT_REFAX` | Transmission unusable; nothing to interpret | system | immediate |

**Ordinal rule:** D4 > D3 > D2 > D1 > D0. A fax that is 95% clear and lacks a signature is D3, not D0.

**D1 is the volume lever.** A blank member ID that is legible on the attached insurance card is not a
phone call. Every D1 must name the artifact and page it was recovered from, or it degrades to D3.

---

## 2. Gate order

Gates run in this order. Cheapest and most decisive first — **a fax that fails G1 never reaches OCR.**

| Gate | Question | Cost |
|------|----------|------|
| G1 Transmission | Did the whole form arrive, right-side-up, once? | page geometry, no OCR |
| G2 Identity / benefit | Is this a real member, and is this their plan? | identifier checks + 270/271 |
| G3 Prescriber validity | Is this a licensed prescriber authorized for this patient? | checksum + registry |
| G4 Clinical plausibility | Does the clinical payload support this drug? | code + drug maps |
| G5 Signature / legal | Is the order legally executed? | region classifier |
| G6 Legibility fallback | For survivors only: resolve ambiguous readings | OCR + lexicon |

---

## 3. Defect classes

| # | Class | Detection | Disposition |
|---|-------|-----------|-------------|
| 3.1 | Partial transmission | **Two distinct modes.** (a) *Clean truncation* — sender scanned only the sheets that were physically present: protocol sees a complete 1-page fax; detectable **only by content** (missing `2 of 2` marker, absent signature block). (b) *Aborted call* — no EOP/DCN after the last page: detectable **at the protocol layer**. | D4 |
| 3.2 | Wrong form version | revision/`OPS-` code, or field-layout fingerprint mismatch | D4 |
| 3.3 | Wrong therapy queue — form sent to the wrong fax number | drug on form vs. inbound DID | auto-route, not a defect |
| 3.4 | Blank required field | field-region emptiness after deskew | D3 if signature/ICD-10/drug; else D1→D3 |
| 3.5 | Invalid NPI | 10 digits, prefix `80840`, Luhn check digit, first digit 1–2 | D2 (candidate list) → D3 |
| 3.6 | Invalid ICD-10 | syntax + existence in code set + drug↔chapter plausibility | D3 |
| 3.7 | Member ID / BIN / PCN mismatch | 270/271 eligibility; known BIN–PCN pairs | D1 (from card) → D3 |
| 3.8 | Quantity math | qty × strength × days-supply vs. SIG | D2 |
| 3.9 | Signature defect — absent, stamped, or wrong signer | signature-region presence + ink-type heuristic; "NO STAMPS" clause | D3 |
| 3.10 | True illegibility | OCR confidence **and** edit distance to formulary/name lexicon | D2 if ≤2 candidates, else D3 |
| 3.11 | Duplicate submission | patient + drug + prescriber + ≤72h window | suppress, not a defect |
| 3.12 | Conditional field absent (e.g. supervising MD for NP/PA, weight for pediatric) | condition table in `field-contract.json` | D3 |

**Principles behind 3.5 and 3.10:** a misread identifier usually *fails its own checksum*. That
converts "illegible" into "provably wrong" with no model. Only fall back to OCR confidence for the
residue — free-text drug names and directions.

---

## 4. Escalation policy

A defect earns a prescriber phone call (D3) only when **all** hold:
1. It is legally or clinically indispensable (signature, ICD-10, drug/strength, member ID), and
2. It cannot be recovered from an attached artifact, and
3. It cannot be narrowed to ≤2 candidates a human could pick in under 60 seconds.

Anything a human can resolve from the page in under a minute is D2, not D3. Calling is the most
expensive recovery path and the one most often used by default.

---

## 5. Non-goals

- Handwriting recognition as a research project. Checksums and lexicon constraints first.
- Field-level OCR confidence as a routing signal. Cross-field consistency is stronger.
- Automating the callback. The goal is to *reduce* D3 volume, not to place robocalls.
- EHR write-back / RPA before defect-class measurement exists.

---

## 6. Measures

| Measure | Definition | Why |
|---------|------------|-----|
| Fax defect rate | % of inbound faxes with ≥1 defect | baseline |
| D3 rate per 100 faxes | prescriber callbacks generated | the cost driver |
| D1 recovery rate | repairs accepted without a call | the lever |
| Time to first touch | inbound → any disposition | operational SLA |
| **False-clear rate** | D0 faxes later found defective | **the only unrecoverable error** |

False-clear is the metric that matters. Every other miss is rework; a false clear is a wrong
medication or a wrong patient. Target is zero, verified by sampling D0 output — not by trusting
the model's own confidence.

---

## 7. PHI boundary

Development and measurement run on synthetic fixtures (`accredo-sample-filled*.pdf`).
Real faxes stay inside the sanitized path; no real member data in test corpora, logs, or prompts.
