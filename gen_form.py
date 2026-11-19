#!/usr/bin/env python3
"""Generate SPECIMEN synthetic Accredo-style referral forms.

No third-party deps: writes PDF content streams directly.
All patient identifiers are fictional (555-01xx numbers, example.com,
ZZTEST surname, SSN 0000).
"""
import sys, struct

W, H = 612.0, 792.0
LEFT, RIGHT = 36.0, 576.0
CW = RIGHT - LEFT

F1, F2, F3, F4, F5, F6 = "F1", "F2", "F3", "F4", "F5", "F6"
FONTS = [
    (F1, "Helvetica", "WinAnsiEncoding"),
    (F2, "Helvetica-Bold", "WinAnsiEncoding"),
    (F3, "Courier", "WinAnsiEncoding"),
    (F4, "Courier-Oblique", "WinAnsiEncoding"),
    (F5, "Helvetica-Oblique", "WinAnsiEncoding"),
    (F6, "Courier-Bold", "WinAnsiEncoding"),
]
REG = "\256"  # (R) in WinAnsi


def esc(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class Canvas:
    def __init__(self):
        self.ops = []

    def line(self, x1, y1, x2, y2, w=0.6, g=0.55):
        self.ops.append(f"{g:.3f} G {w:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=0.7):
        if fill is not None:
            self.ops.append(f"{fill:.3f} g {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")
        if stroke is not None:
            self.ops.append(f"{stroke:.3f} G {lw:.2f} w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    def box(self, x, y, s=7.0, checked=False, g=0.1):
        self.rect(x, y, s, s, stroke=g, lw=0.8)
        if checked:
            self.line(x + 1.2, y + s / 2 - 0.6, x + s * 0.42, y + 1.1, 0.9, 0.05)
            self.line(x + s * 0.42, y + 1.1, x + s - 0.9, y + s - 1.1, 0.9, 0.05)
        return x + s + 3

    def text(self, x, y, s, font=F1, size=9.0, g=0.05):
        self.ops.append(
            f"BT /{font} {size:.2f} Tf {g:.3f} g {x:.2f} {y:.2f} Td ({esc(s)}) Tj ET"
        )

    def content(self):
        return "\n".join(self.ops).encode("latin-1")


def field(c, x, y, w, label, value, size=8.6, lab_g=0.38):
    if label:
        c.text(x, y + 10.5, label, F5, 6.2, lab_g)
    c.line(x, y, x + w, y, 0.6, 0.62)
    if value:
        c.text(x + 2.5, y + 2.6, value, F3, size, 0.05)


def row(c, y, specs, gap=8.0, dy=27.0):
    x = LEFT
    for label, value, w in specs:
        field(c, x, y, w, label, value)
        x += w + gap
    return y - dy


def section(c, y, num, title):
    c.rect(LEFT, y, CW, 15, fill=0.86)
    c.rect(LEFT, y, 15, 15, fill=0.30)
    c.text(LEFT + 3.6, y + 4.4, num, F2, 9.0, 1.0)
    c.text(LEFT + 21, y + 4.4, title, F2, 8.8, 0.08)
    return y - 20


def fax_stamp_line(c, page_label):
    c.line(LEFT, 774, RIGHT, 774, 0.5, 0.45)
    c.text(LEFT, 777,
           f"11/17/2026 09:44  FROM: SPRINGFIELD RHEUMATOLOGY ASSOC    FAX: (555) 010-0201    {page_label}",
           F3, 6.4, 0.35)
    c.line(LEFT, 783, RIGHT, 783, 0.5, 0.45)


def header(c, fax_stamp):
    if fax_stamp:
        fax_stamp_line(c, "P.01/02")
    c.rect(LEFT, 750, CW, 13, fill=0.90)
    c.text(LEFT + 4, 754.4, "SPECIMEN  -  SYNTHETIC TEST DATA  -  NOT A REAL PATIENT RECORD  -  DO NOT SUBMIT", F6, 6.9, 0.25)
    c.text(LEFT, 735, "Please fax ALL pages of completed form to your team at 888.302.1028.", F2, 8.6, 0.05)
    c.text(LEFT, 724.5, "To reach your team, call toll-free 844.516.3319.", F1, 8.0, 0.15)
    c.text(LEFT, 706, "Accredo" + REG + " Specialty Pharmacy Prescription & Enrollment Form", F2, 13.2, 0.02)
    c.text(LEFT, 694.5, "Four simple steps to submit your referral.", F5, 8.3, 0.30)
    c.line(LEFT, 688, RIGHT, 688, 1.0, 0.30)
    return 676


def footer(c, page, fax_stamp):
    c.line(LEFT, 74, RIGHT, 74, 0.5, 0.65)
    c.text(LEFT, 63, "SPECIMEN ONLY - synthetic identifiers (555-01xx phones, example.com, SSN 0000).", F5, 6.4, 0.40)
    c.text(LEFT, 54, "Not a valid prescription. Generated as a layout/OCR test fixture, not an official Accredo document.", F5, 6.4, 0.40)
    c.text(RIGHT - 62, 63, f"Page {page} of 2", F3, 7.2, 0.35)
    c.text(RIGHT - 96, 54, "Fax: 888.302.1028", F3, 7.2, 0.35)


def page1(fax_stamp):
    c = Canvas()
    y = header(c, fax_stamp)

    y = section(c, y, "1", "PATIENT INFORMATION")
    c.text(LEFT, y + 4, "Please provide copies of front and back of all medical and prescription insurance cards.", F5, 7.2, 0.35)
    y -= 14
    x = c.box(LEFT, y, checked=True)
    c.text(x, y + 1.2, "New patient", F1, 8.4, 0.1)
    x = c.box(x + 74, y, checked=False)
    c.text(x, y + 1.2, "Current patient", F1, 8.4, 0.1)
    y -= 22

    y = row(c, y, [("Patient's first name", "Jane", 168), ("Last name", "ZZTEST", 196),
                   ("Middle initial", "Q", 68), ("Last 4 digits of SSN", "0000", 92)])
    y = row(c, y, [("Date of birth", "01/01/1980", 118), ("Sex at birth", "X  Female", 118),
                   ("Gender identity", "Female", 118), ("Pronouns", "she/her", 162)])
    y = row(c, y, [("Street address", "123 Test Lane", 392), ("Apt #", "4", 132)])
    y = row(c, y, [("City", "Springfield", 232), ("State", "IL", 88), ("Zip", "62701", 132)])
    y = row(c, y, [("Home phone", "(555) 010-0100", 152), ("Cell phone", "(555) 010-0101", 152),
                   ("Email address", "jane.zztest@example.com", 220)])
    y = row(c, y, [("Parent/guardian (if applicable)", "N/A", 320), ("Home phone", "N/A", 212)])
    y = row(c, y, [("Alternate caregiver/contact", "N/A - no message", 320), ("Cell phone", "N/A", 212)])
    y = row(c, y, [("Patient's primary language", "X  English", 210), ("If other, please specify", "-", 322)])

    y += 12
    c.text(LEFT, y, "INSURANCE", F2, 7.4, 0.25)
    c.line(LEFT + 56, y + 2, RIGHT, y + 2, 0.5, 0.72)
    y -= 22
    y = row(c, y, [("Medical insurance plan", "BlueCross BlueShield IL PPO", 190),
                   ("Member ID", "XQZ0000000001", 170), ("Group #", "00001234", 140)])
    y = row(c, y, [("Prescription plan", "Express Scripts", 190), ("Rx BIN", "610014", 110),
                   ("Rx PCN", "IRONWOOD", 110), ("Policy holder", "Jane Q. ZZTEST", 100)])

    y -= 6
    y = section(c, y, "2", "PRESCRIBER INFORMATION")
    c.text(LEFT, y + 4, "All fields must be completed to expedite prescription fulfillment.", F5, 7.2, 0.35)
    y -= 14

    y = row(c, y, [("Date", "11/17/2026", 100), ("Time", "09:42", 84),
                   ("Date medication needed", "11/20/2026", 150), ("", "", 190)])
    y = row(c, y, [("Office/clinic/institution name", "Springfield Rheumatology Associates, P.C.", 532)])
    y = row(c, y, [("Prescriber's first name", "Alex", 130), ("Last name", "SAMPLE", 150),
                   ("Prescriber's title", "MD", 96), ("If NP or PA, under direction of Dr.", "N/A", 140)])
    y = row(c, y, [("Office phone", "(555) 010-0200", 150), ("Fax", "(555) 010-0201", 130),
                   ("NPI #", "1234567893", 130), ("License #", "IL-036-000000", 106)])
    y = row(c, y, [("Office contact and title", "M. Rivera, Referral Coordinator", 300),
                   ("Office contact email", "referrals@example.com", 232)])
    y = row(c, y, [("Office street address", "500 Sample Blvd, Suite 210", 392),
                   ("Suite #", "210", 132)])
    y = row(c, y, [("City", "Springfield", 232), ("State", "IL", 88), ("Zip", "62701", 132)])

    y += 12
    c.text(LEFT, y, "Deliver product to:", F2, 7.6, 0.2)
    x = c.box(LEFT + 92, y - 0.6, checked=True)
    c.text(x, y, "Patient's home", F1, 8.2, 0.1)
    x = c.box(x + 92, y - 0.6, checked=False)
    c.text(x, y, "Prescriber's office", F1, 8.2, 0.1)
    x = c.box(x + 112, y - 0.6, checked=False)
    c.text(x, y, "Clinic / infusion site", F1, 8.2, 0.1)

    footer(c, 1, fax_stamp)
    return c


def page2(fax_stamp):
    c = Canvas()
    # compact repeated header
    if fax_stamp:
        fax_stamp_line(c, "P.02/02")
    c.rect(LEFT, 748, CW, 13, fill=0.90)
    c.text(LEFT + 4, 752.4, "SPECIMEN  -  SYNTHETIC TEST DATA  -  NOT A REAL PATIENT RECORD  -  DO NOT SUBMIT", F6, 6.9, 0.25)
    c.text(LEFT, 733, "Accredo" + REG + " Specialty Pharmacy Prescription & Enrollment Form", F2, 9.6, 0.05)
    c.text(LEFT, 724, "Fax completed form to 888.302.1028.", F2, 8.2, 0.10)
    c.line(LEFT, 718, RIGHT, 718, 1.0, 0.30)

    y = 700
    y = row(c, y, [("Patient's first name", "Jane", 130), ("Last name", "ZZTEST", 140),
                   ("Middle initial", "Q", 80), ("Date of birth", "01/01/1980", 158)], dy=26)
    y = row(c, y, [("Prescriber's first name", "Alex", 130), ("Last name", "SAMPLE", 140),
                   ("Phone", "(555) 010-0200", 238)], dy=30)

    y = section(c, y, "3", "CLINICAL INFORMATION")
    y -= 2
    y = row(c, y, [("Primary ICD-10 code (REQUIRED)", "M05.79", 130), ("Weight (kg)", "68.4", 96),
                   ("Height (cm)", "165", 96), ("Date measured", "11/17/2026", 178)], dy=28)
    y += 6
    x = c.box(LEFT, y, checked=True)
    c.text(x, y + 1.2, "NKDA", F1, 8.2, 0.1)
    x = c.box(x + 54, y, checked=False)
    c.text(x, y + 1.2, "Known drug allergies:", F1, 8.2, 0.1)
    c.text(x + 92, y + 1.0, "Sulfa - rash (2019)", F3, 8.4, 0.05)
    y -= 4
    c.text(LEFT, y - 8, "Concurrent meds:", F5, 6.2, 0.38)
    c.line(LEFT, y - 20, RIGHT, y - 20, 0.6, 0.62)
    c.text(LEFT + 2.5, y - 17.5, "methotrexate 15 mg PO weekly; folic acid 1 mg PO daily; prednisone 5 mg PO daily", F3, 8.6, 0.05)
    y -= 40

    y = section(c, y, "4", "PRESCRIBING INFORMATION")
    y -= 2

    # table
    cols = [(LEFT, 158), (LEFT + 164, 124), (LEFT + 294, 160), (LEFT + 460, 80)]
    top = y
    c.rect(LEFT, top - 13, CW, 13, fill=0.93)
    heads = ["Medication", "Strength/Formulation", "Directions", "Quantity/Refills"]
    for (cx, cwid), htxt in zip(cols, heads):
        c.text(cx + 3, top - 9.4, htxt, F2, 6.8, 0.15)
    ry = top - 13
    c.line(LEFT, ry, RIGHT, ry, 0.8, 0.35)
    data = [
        ("adalimumab 40 mg/0.8 mL", "Prefilled pen", "40 mg subcut every other week", "2 pens / 5 rfl"),
        ("", "", "", ""),
        ("", "", "", ""),
    ]
    rh = 30
    for i, cols_data in enumerate(data):
        ry -= rh
        for (cx, cwid), val in zip(cols, cols_data):
            if val:
                c.text(cx + 3, ry + 11, val, F3, 7.6, 0.05)
        c.line(LEFT, ry, RIGHT, ry, 0.6, 0.55)
    for (cx, cwid) in cols[:-1]:
        c.line(cx + cwid + 3, top - 13, cx + cwid + 3, ry, 0.5, 0.70)
    c.rect(LEFT, ry, CW, top - ry, stroke=0.35, lw=0.8)

    ry -= 20
    c.text(LEFT, ry, "Dispense:", F2, 7.6, 0.2)
    x = c.box(LEFT + 48, ry - 0.6, checked=True)
    c.text(x, ry, "1-month supply", F1, 8.0, 0.1)
    x = c.box(x + 86, ry - 0.6, checked=False)
    c.text(x, ry, "3-month supply", F1, 8.0, 0.1)
    x = c.box(x + 86, ry - 0.6, checked=False)
    c.text(x, ry, "Other", F1, 8.0, 0.1)
    c.line(x + 32, ry - 1.5, x + 130, ry - 1.5, 0.6, 0.6)
    c.text(x + 140, ry, "Refills:", F2, 7.6, 0.2)
    c.text(x + 176, ry, "5", F3, 8.4, 0.05)

    ry -= 18
    x = c.box(LEFT, ry - 0.6, checked=True)
    c.text(x, ry, "Prescriber, please check here to authorize ancillary supplies (needles, syringes, sterile water, etc.)", F1, 7.4, 0.12)

    ry -= 26
    c.rect(LEFT, ry - 62, CW, 62, stroke=0.45, lw=0.9)
    c.text(LEFT + 8, ry - 12, "Prescriber's signature required (sign below)  -  Physician attests this is his/her legal signature. NO STAMPS.", F2, 7.0, 0.15)
    c.text(LEFT + 8, ry - 22, "SIGN", F2, 7.2, 0.35)
    c.text(LEFT + 8, ry - 31, "HERE", F2, 7.2, 0.35)
    c.text(LEFT + 66, ry - 33, "/Alex Sample MD/", F4, 13.0, 0.10)
    c.line(LEFT + 60, ry - 36, LEFT + 250, ry - 36, 0.8, 0.30)
    c.text(LEFT + 62, ry - 45, "Prescriber's signature", F5, 6.2, 0.40)
    c.line(LEFT + 268, ry - 36, LEFT + 356, ry - 36, 0.8, 0.30)
    c.text(LEFT + 292, ry - 33, "11/17/2026", F3, 8.4, 0.05)
    c.text(LEFT + 270, ry - 45, "Date", F5, 6.2, 0.40)
    x = c.box(LEFT + 380, ry - 30, checked=True)
    c.text(x, ry - 29, "Dispense as written", F1, 7.4, 0.12)
    x = c.box(LEFT + 380, ry - 44, checked=False)
    c.text(x, ry - 43, "Substitution allowed", F1, 7.4, 0.12)

    ry -= 74
    c.text(LEFT, ry, "The prescriber is to comply with his/her state-specific prescription requirements such as e-prescribing,", F5, 6.6, 0.42)
    c.text(LEFT, ry - 9, "state-specific prescription form, fax language, etc. Non-compliance may result in outreach to the prescriber.", F5, 6.6, 0.42)

    ry -= 28
    c.rect(LEFT, ry - 62, CW, 62, stroke=0.55, lw=0.7)
    c.text(LEFT + 8, ry - 13, "DOCUMENTATION ENCLOSED WITH THIS FAX", F2, 7.0, 0.20)
    items = [
        (LEFT + 10, ry - 28, True, "Signed prescription (page 2 of this form)"),
        (LEFT + 10, ry - 41, True, "Front and back of medical and Rx cards"),
        (LEFT + 286, ry - 28, True, "Clinical notes / most recent labs"),
        (LEFT + 286, ry - 41, False, "Prior authorization approval (if on file)"),
    ]
    for ix, iy, checked, label in items:
        bx = c.box(ix, iy - 1, s=6.6, checked=checked)
        c.text(bx, iy, label, F1, 7.2, 0.12)

    footer(c, 2, fax_stamp)
    return c


class PDFBuilder:
    def __init__(self):
        self.entries = []

    def add(self, b):
        if isinstance(b, str):
            b = b.encode("latin-1")
        self.entries.append(b)
        return len(self.entries)

    def out(self):
        buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offs = [0]
        for i, b in enumerate(self.entries, 1):
            offs.append(len(buf))
            buf += f"{i} 0 obj\n".encode() + b + b"\nendobj\n"
        xref = len(buf)
        n = len(self.entries) + 1
        buf += f"xref\n0 {n}\n".encode() + b"0000000000 65535 f \n"
        for off in offs[1:]:
            buf += f"{off:010d} 00000 n \n".encode()
        buf += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(buf)


def build(fax_stamp=False):
    b = PDFBuilder()
    b.add("<< /Type /Catalog /Pages 2 0 R >>")
    b.add("PLACEHOLDER_PAGES")
    fnum = {}
    for tag, base, enc in FONTS:
        fnum[tag] = b.add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /{enc} >>")
    pages = []
    for c in (page1(fax_stamp), page2(fax_stamp)):
        cnum = b.add(f"<< /Length {len(c.content())} >>\nstream\n".encode()
                     + c.content() + b"\nendstream")
        pnum = b.add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
            f"/Resources << /Font << " +
            " ".join(f"/{t} {fnum[t]} 0 R" for t, _, _ in FONTS) +
            " >> >> /Contents %d 0 R >>" % cnum
        )
        pages.append(pnum)
    b.entries[1] = (f"<< /Type /Pages /Count {len(pages)} /Kids ["
                    + " ".join(f"{p} 0 R" for p in pages) + "] >>").encode()
    return b.out()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    stamp = "--fax" in sys.argv
    with open(out, "wb") as f:
        f.write(build(stamp))
    print("wrote", out, "fax_stamp=%s" % stamp)
