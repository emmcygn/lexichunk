"""Generate tests/fixtures/uk_pdf_extracted_agreement.txt and its gold annotation.

This fixture simulates a UK services agreement as it would look after being
pulled out of a PDF by a naive text extractor: a running header/footer pair
repeats every ``page_lines`` body lines, prose is hard-wrapped at a fixed
78-column width with no long-word breaking, and one occurrence of
"indemnification" is forced to break across a soft hyphen ("indemnifi-" /
"cation"). Together these exercise lexichunk's tolerance for page furniture,
mid-sentence line breaks, and hyphenated words that split a cross-reference
or a defined term across two lines.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _emit import Clause, emit, write

NAME = "uk_pdf_extracted_agreement"

PREAMBLE = [
    "SERVICES AGREEMENT",
    "This Agreement is made on 1 March 2024 between Atlas Managed Services "
    'Limited, a company incorporated in England and Wales with company '
    'number 08123456 and whose registered office is at 25 Old Broad Street, '
    'London EC2N 1HN (the "Supplier"), and Meridian Retail Group PLC, a '
    "company incorporated in England and Wales with company number "
    '05678910 and whose registered office is at 100 Victoria Street, '
    'London SW1E 5JL (the "Customer").',
    "The Supplier has agreed to provide, and the Customer has agreed to "
    "receive, the Services on the terms of this Agreement. IT IS AGREED as "
    "follows:",
]

CLAUSES: list[Clause] = [
    Clause("1", "1. Definitions and Interpretation", 0, None),
    Clause(
        "1.1",
        "1.1 Definitions",
        1,
        "1",
        paragraphs=[
            'In this Agreement, the following terms have the meanings set '
            "out below.",
            '"Business Day" means a day other than a Saturday, Sunday or '
            "public holiday in England and Wales, on which clearing banks "
            "are open for general business in London;",
            '"Charges" means the charges payable by the Customer to the '
            "Supplier for the Services, as set out in Schedule 2;",
            '"Commencement Date" means 1 April 2024;',
            '"Confidential Information" means any information disclosed by '
            "one party to the other, whether orally, in writing or in any "
            "other form, that is designated as confidential or that a "
            "reasonable person would understand to be confidential given "
            "its nature and the circumstances of disclosure;",
            '"Deliverables" means any reports, documentation, code or '
            "other materials created or supplied by the Supplier for the "
            "Customer in the course of providing the Services;",
            '"Force Majeure Event" means any event beyond the reasonable '
            "control of the affected party, including fire, flood, "
            "industrial action, failure of a utility service or an act of "
            "government, which prevents or delays that party from "
            "performing its obligations under this Agreement;",
            '"Intellectual Property Rights" means patents, rights to '
            "inventions, copyright, trade marks, design rights, database "
            "rights and all other intellectual property rights, whether "
            "registered or unregistered, together with applications for "
            "any of the foregoing;",
            '"Personal Data" means personal data, as that term is defined '
            "in the Data Protection Legislation, that is processed by the "
            "Supplier on behalf of the Customer in connection with the "
            "Services;",
            '"Services" means the managed hosting, support and '
            "professional services described in Schedule 1;",
            '"Term" means the period beginning on the Commencement Date '
            "and continuing until this Agreement is terminated in "
            "accordance with clause 11.",
        ],
    ),
    Clause(
        "1.2",
        "1.2 Interpretation",
        1,
        "1",
        paragraphs=[
            "In this Agreement, unless the context otherwise requires, a "
            "reference to a person includes an individual, company, "
            "partnership or unincorporated body, and a reference to a "
            "statute includes that statute as amended, re-enacted or "
            "replaced from time to time.",
        ],
    ),
    # An inline sub-clause list: each item's whole text is its heading line,
    # wrapped across several lines.  Declared as clauses rather than as
    # paragraphs of 1.2 because that is what they are, and the gold has to
    # agree with the document rather than with whichever is easier to emit.
    Clause(
        "(a)",
        "(a) references to clauses and Schedules are references to clauses "
        "of, and Schedules to, this Agreement;",
        3,
        "1.2",
    ),
    Clause(
        "(b)",
        "(b) the headings in this Agreement are for convenience only and do "
        "not affect its interpretation;",
        3,
        "1.2",
    ),
    Clause(
        "(c)",
        "(c) the singular includes the plural and vice versa, and words "
        "importing one gender include every gender; and",
        3,
        "1.2",
    ),
    Clause(
        "(d)",
        "(d) any words following the terms including, in particular or any "
        "similar expression are illustrative and do not limit the generality "
        "of the words preceding them; and",
        3,
        "1.2",
    ),
    Clause(
        "(e)",
        "(e) if there is a conflict between the terms of the main body of "
        "this Agreement and any Schedule, the terms of the main body of this "
        "Agreement shall prevail unless the Schedule expressly states "
        "otherwise.",
        3,
        "1.2",
    ),
    Clause("2", "2. Commencement and Term", 0, None),
    Clause(
        "2.1",
        "2.1 Commencement",
        1,
        "2",
        paragraphs=[
            "This Agreement shall commence on the Commencement Date and "
            "shall continue, subject to earlier termination in accordance "
            "with clause 11, for the initial period set out in Schedule "
            "2. The Supplier shall have no obligation to provide the "
            "Services before the Commencement Date, and any services "
            "provided before that date shall be provided on a goodwill "
            "basis only, without charge and without liability."
        ],
    ),
    Clause(
        "2.2",
        "2.2 Term and Renewal",
        1,
        "2",
        paragraphs=[
            "The Term shall continue for an initial period of thirty-six "
            "months from the Commencement Date and shall automatically "
            "renew for successive periods of twelve months, unless either "
            "party gives the other not less than ninety days' written "
            "notice of non-renewal before the expiry of the "
            "then-current period. Nothing in this clause 2.2 obliges "
            "either party to agree to any variation of the Charges as a "
            "condition of renewal, and the parties shall negotiate any "
            "proposed variation in good faith."
        ],
    ),
    Clause(
        "2.3",
        "2.3 Extension of Term",
        1,
        "2",
        paragraphs=[
            "The parties may agree in writing to extend the Term on such "
            "further terms as they may agree, and any such extension "
            "shall be recorded in a written amendment signed by an "
            "authorised representative of each party. During any "
            "extension of the Term, all other terms of this Agreement "
            "shall continue to apply in full force and effect, save to "
            "the extent the parties expressly agree otherwise in "
            "writing."
        ],
    ),
    Clause("3", "3. Supplier Obligations", 0, None),
    Clause(
        "3.1",
        "3.1 General Obligations",
        1,
        "3",
        paragraphs=[
            "The Supplier shall provide the Services with reasonable "
            "skill and care and in accordance with good industry "
            "practice applicable to the provision of services of a "
            "similar nature. The Supplier shall ensure that the Services "
            "are performed by appropriately qualified and experienced "
            "personnel. The Supplier shall comply with all applicable "
            "laws and regulations in the performance of the Services and "
            "shall maintain such professional indemnity and public "
            "liability insurance as is reasonable having regard to the "
            "nature and scale of the Services."
        ],
    ),
    Clause(
        "3.2",
        "3.2 Standard of Performance",
        1,
        "3",
        paragraphs=[
            "The Supplier shall use reasonable endeavours to meet any "
            "performance targets set out in Schedule 1, and shall notify "
            "the Customer promptly of any circumstance that is likely to "
            "have a material adverse effect on the Supplier's ability to "
            "perform the Services, having regard to the Customer's "
            "cooperation obligations under clause 4.1."
        ],
    ),
    Clause(
        "3.3",
        "3.3 Personnel and Subcontracting",
        1,
        "3",
        paragraphs=[
            "The Supplier may subcontract the performance of any part of "
            "the Services, provided that the Supplier remains liable for "
            "the acts and omissions of its subcontractors as if they "
            "were its own acts and omissions."
        ],
    ),
    Clause("4", "4. Customer Obligations", 0, None),
    Clause(
        "4.1",
        "4.1 Cooperation and Access",
        1,
        "4",
        paragraphs=[
            "The Customer shall provide the Supplier with such "
            "information, access and cooperation as the Supplier "
            "reasonably requires to perform the Services, including "
            "timely access to the Customer's premises, systems and "
            "personnel where relevant."
        ],
    ),
    Clause(
        "4.2",
        "4.2 Customer Systems",
        1,
        "4",
        paragraphs=[
            "The Customer shall be responsible for procuring and "
            "maintaining the network connectivity, hardware and software "
            "environment necessary to receive the Services, except to "
            "the extent expressly agreed otherwise in Schedule 1."
        ],
    ),
    Clause(
        "4.3",
        "4.3 Delay by the Customer",
        1,
        "4",
        paragraphs=[
            "If the Supplier's performance of its obligations is "
            "prevented or delayed by any act or omission of the "
            "Customer, the Supplier shall not be liable for the "
            "resulting delay, and the relevant milestone or delivery "
            "date shall be extended by a reasonable period."
        ],
    ),
    Clause("5", "5. Charges and Payment", 0, None),
    Clause(
        "5.1",
        "5.1 Charges",
        1,
        "5",
        paragraphs=[
            "The Customer shall pay the Charges to the Supplier in "
            "accordance with Schedule 2. The Charges are exclusive of "
            "value added tax, which shall be payable in addition at the "
            "applicable rate."
        ],
    ),
    Clause(
        "5.2",
        "5.2 Invoicing and Payment Terms",
        1,
        "5",
        paragraphs=[
            "The Supplier shall invoice the Customer monthly in arrears, "
            "and the Customer shall pay each undisputed invoice within "
            "thirty days of the date of a valid invoice, in accordance "
            "with the payment terms set out in paragraph 2 of "
            "Schedule 2."
        ],
    ),
    Clause(
        "5.3",
        "5.3 Late Payment",
        1,
        "5",
        paragraphs=[
            "If the Customer fails to pay any undisputed amount by the "
            "due date, the Supplier may charge interest on the overdue "
            "amount at the rate of four per cent per annum above the "
            "Bank of England base rate, accruing daily from the due date "
            "until payment is made in full."
        ],
    ),
    Clause(
        "5.4",
        "5.4 VAT",
        1,
        "5",
        paragraphs=[
            "All amounts stated in this Agreement are exclusive of VAT, "
            "and the Customer shall pay any VAT properly chargeable in "
            "connection with the Charges at the rate and in the manner "
            "prescribed by applicable law."
        ],
    ),
    Clause("6", "6. Confidentiality", 0, None),
    Clause(
        "6.1",
        "6.1 Confidentiality Obligations",
        1,
        "6",
        paragraphs=[
            "Each party shall keep confidential all Confidential "
            "Information disclosed to it by the other party and shall "
            "not use such Confidential Information except for the "
            "purpose of performing its obligations under this Agreement."
        ],
    ),
    Clause(
        "6.2",
        "6.2 Permitted Disclosures",
        1,
        "6",
        paragraphs=[
            "A party may disclose Confidential Information to its "
            "employees, officers, professional advisers and "
            "subcontractors who need to know the information for the "
            "purposes set out in clause 6.1, provided that it procures "
            "that such persons comply with confidentiality obligations "
            "equivalent to those in this clause 6."
        ],
    ),
    Clause(
        "6.3",
        "6.3 Duration of Obligations",
        1,
        "6",
        paragraphs=[
            "The obligations in this clause 6 shall survive termination "
            "or expiry of this Agreement for a period of five years, "
            "except in respect of Confidential Information that "
            "constitutes a trade secret, for which the obligations shall "
            "continue indefinitely."
        ],
    ),
    Clause("7", "7. Data Protection", 0, None),
    Clause(
        "7.1",
        "7.1 Data Processing",
        1,
        "7",
        paragraphs=[
            "To the extent that the Supplier processes Personal Data on "
            "behalf of the Customer in connection with the Services, the "
            "Supplier shall process that Personal Data only in "
            "accordance with the Customer's documented instructions and "
            "the requirements of the Data Protection Legislation."
        ],
    ),
    Clause(
        "7.2",
        "7.2 Security Measures",
        1,
        "7",
        paragraphs=[
            "The Supplier shall implement appropriate technical and "
            "organisational measures to protect Personal Data against "
            "unauthorised or unlawful processing and against accidental "
            "loss, destruction or damage, having regard to the state of "
            "the art and the cost of implementation."
        ],
    ),
    Clause(
        "7.3",
        "7.3 Sub-Processors",
        1,
        "7",
        paragraphs=[
            "The Supplier shall not engage any sub-processor to process "
            "Personal Data without the prior written authorisation of "
            "the Customer, and shall impose on any authorised "
            "sub-processor obligations no less protective than those set "
            "out in clause 7.2."
        ],
    ),
    Clause("8", "8. Intellectual Property", 0, None),
    Clause(
        "8.1",
        "8.1 Ownership",
        1,
        "8",
        paragraphs=[
            "Except as expressly provided in this clause 8, all "
            "Intellectual Property Rights in the Deliverables and in any "
            "materials, tools or methodologies used by the Supplier in "
            "providing the Services shall vest in, and remain the "
            "property of, the Supplier."
        ],
    ),
    Clause(
        "8.2",
        "8.2 Licence",
        1,
        "8",
        paragraphs=[
            "The Supplier grants to the Customer a non-exclusive, "
            "non-transferable licence to use the Deliverables for the "
            "Customer's internal business purposes for the duration of "
            "the Term."
        ],
    ),
    Clause(
        "8.3",
        "8.3 Third Party Rights",
        1,
        "8",
        paragraphs=[
            "The Supplier warrants that the Deliverables, when used in "
            "accordance with this Agreement, will not infringe the "
            "Intellectual Property Rights of any third party, save to "
            "the extent that any infringement arises from materials "
            "supplied by the Customer."
        ],
    ),
    Clause("9", "9. Indemnities", 0, None),
    Clause(
        "9.1",
        "9.1 Supplier Indemnity",
        1,
        "9",
        paragraphs=[
            "The Supplier shall indemnify the Customer against all "
            "losses, liabilities and reasonable costs incurred by the "
            "Customer arising from any third party claim that the "
            "Deliverables infringe that third party's Intellectual "
            "Property Rights, save to the extent excluded under "
            "clause 10."
        ],
    ),
    Clause(
        "9.2",
        "9.2 Customer Indemnity",
        1,
        "9",
        paragraphs=[
            "The Customer shall indemnify the Supplier against all "
            "losses, liabilities and reasonable costs incurred by the "
            "Supplier arising from the Customer's breach of clause 6.1 "
            "or from materials supplied by the Customer for "
            "incorporation into the Deliverables."
        ],
    ),
    Clause(
        "9.3",
        "9.3 Conduct of Claims",
        1,
        "9",
        paragraphs=[
            "The indemnities in clause 9.1 and clause 9.2 are subject to "
            "the conduct of claims procedure set out in this clause 9, "
            "including the right to seek indemnification for losses as "
            "described further in clause 9.3(b) below."
        ],
    ),
    Clause(
        "(a)",
        "(a) Notification",
        3,
        "9.3",
        paragraphs=[
            "The party seeking indemnification shall notify the "
            "indemnifying party promptly in writing on becoming aware of "
            "a claim."
        ],
    ),
    Clause(
        "(b)",
        "(b) Control of Defence",
        3,
        "9.3",
        paragraphs=[
            "The indemnifying party may assume control of the defence "
            "and settlement of the claim, provided that it acts "
            "reasonably and keeps the indemnified party informed of "
            "material developments."
        ],
    ),
    Clause(
        "(c)",
        "(c) Cooperation",
        3,
        "9.3",
        paragraphs=[
            "The indemnified party shall provide reasonable cooperation "
            "and assistance to the indemnifying party, at the "
            "indemnifying party's expense, in the defence or settlement "
            "of the claim."
        ],
    ),
    Clause("10", "10. Limitation of Liability", 0, None),
    Clause(
        "10.1",
        "10.1 Exclusions",
        1,
        "10",
        paragraphs=[
            "Subject to clause 10.3, neither party shall be liable to "
            "the other for any indirect or consequential loss, or for "
            "any loss of profits, revenue, business opportunity or "
            "goodwill, arising out of or in connection with this "
            "Agreement."
        ],
    ),
    Clause(
        "10.2",
        "10.2 Financial Cap",
        1,
        "10",
        paragraphs=[
            "Subject to clause 10.3, the total aggregate liability of "
            "each party arising out of or in connection with this "
            "Agreement, whether in contract, tort or otherwise, shall "
            "not exceed an amount equal to the total Charges paid or "
            "payable in the twelve months preceding the event giving "
            "rise to the claim."
        ],
    ),
    Clause(
        "10.3",
        "10.3 Unlimited Liability",
        1,
        "10",
        paragraphs=[
            "Nothing in this Agreement shall exclude or limit either "
            "party's liability for death or personal injury caused by "
            "negligence, for fraud or fraudulent misrepresentation, or "
            "for any other liability that cannot lawfully be excluded or "
            "limited."
        ],
    ),
    Clause("11", "11. Termination", 0, None),
    Clause(
        "11.1",
        "11.1 Termination for Convenience",
        1,
        "11",
        paragraphs=[
            "Either party may terminate this Agreement for convenience "
            "by giving the other not less than ninety days' written "
            "notice, such notice not to expire earlier than the first "
            "anniversary of the Commencement Date."
        ],
    ),
    Clause(
        "11.2",
        "11.2 Termination for Cause",
        1,
        "11",
        paragraphs=[
            "Either party may terminate this Agreement with immediate "
            "effect by written notice to the other if the other party "
            "commits a material breach of this Agreement that is not "
            "remedied within thirty days of being notified in writing to "
            "do so, or becomes insolvent."
        ],
    ),
    Clause(
        "11.3",
        "11.3 Consequences of Termination",
        1,
        "11",
        paragraphs=[
            "On termination or expiry of this Agreement for any reason, "
            "the Customer shall pay all Charges accrued but unpaid as at "
            "the date of termination, and each party shall return or "
            "destroy the other party's Confidential Information in "
            "accordance with clause 6."
        ],
    ),
    Clause(
        "11.4",
        "11.4 Force Majeure",
        1,
        "11",
        paragraphs=[
            "Neither party shall be liable for any failure or delay in "
            "performing its obligations under this Agreement to the "
            "extent that the failure or delay is caused by a Force "
            "Majeure Event, provided that the affected party notifies "
            "the other party promptly and uses reasonable endeavours to "
            "mitigate the effect of the Force Majeure Event."
        ],
    ),
    Clause("12", "12. Governing Law and Jurisdiction", 0, None),
    Clause(
        "12.1",
        "12.1 Governing Law",
        1,
        "12",
        paragraphs=[
            "This Agreement, and any dispute or claim arising out of or "
            "in connection with it, its subject matter or its "
            "formation, shall be governed by and construed in accordance "
            "with the law of England and Wales."
        ],
    ),
    Clause(
        "12.2",
        "12.2 Jurisdiction",
        1,
        "12",
        paragraphs=[
            "The parties irrevocably agree that the courts of England "
            "and Wales shall have exclusive jurisdiction to settle any "
            "dispute or claim arising out of or in connection with this "
            "Agreement, its subject matter or its formation."
        ],
    ),
    Clause(
        "Schedule 1",
        "Schedule 1 — Services Description",
        -1,
        None,
    ),
    Clause(
        "1",
        "1. Scope of Services",
        0,
        "Schedule 1",
        paragraphs=[
            "The Services comprise the managed hosting, monitoring, "
            "support and professional services described in this "
            "Schedule 1, together with such additional services as the "
            "parties may agree in writing from time to time, all as "
            "further described in clause 1.1."
        ],
    ),
    Clause(
        "2",
        "2. Service Levels",
        0,
        "Schedule 1",
        paragraphs=[
            "The Supplier shall use reasonable endeavours to achieve the "
            "service levels set out below, including a target monthly "
            "uptime of 99.5% for the hosted environment, measured using "
            "the Supplier's standard monitoring tools."
        ],
    ),
    Clause(
        "3",
        "3. Change Control",
        0,
        "Schedule 1",
        paragraphs=[
            "Either party may request a change to the Services by "
            "written notice, and no change shall take effect unless "
            "agreed in writing by both parties and, where the change "
            "affects the Charges, reflected in an updated version of "
            "Schedule 2."
        ],
    ),
    Clause(
        "Schedule 2",
        "Schedule 2 — Charges and Payment Schedule",
        -1,
        None,
    ),
    Clause(
        "1",
        "1. Charges",
        0,
        "Schedule 2",
        paragraphs=[
            "The annual Charges for the Services are £36,000, "
            "payable in accordance with clause 5.2, and shall be "
            "reviewed annually in accordance with paragraph 3 of this "
            "Schedule 2."
        ],
    ),
    Clause(
        "2",
        "2. Payment Terms",
        0,
        "Schedule 2",
        paragraphs=[
            "Invoices shall be issued monthly in arrears and are payable "
            "within thirty days of the invoice date, as further "
            "described in clause 5.2, time being of the essence in "
            "respect of payment."
        ],
    ),
    Clause(
        "3",
        "3. Annual Review",
        0,
        "Schedule 2",
        paragraphs=[
            "The Charges shall be reviewed on each anniversary of the "
            "Commencement Date and may be increased by the Supplier by "
            "no more than the percentage increase in the Consumer Prices "
            "Index over the preceding twelve months."
        ],
    ),
]

DEFINED_TERMS = {
    "Business Day": (
        "a day other than a Saturday, Sunday or public holiday in "
        "England and Wales, on which clearing banks are open for "
        "general business in London"
    ),
    "Charges": (
        "the charges payable by the Customer to the Supplier for the "
        "Services, as set out in Schedule 2"
    ),
    "Commencement Date": "1 April 2024",
    "Confidential Information": (
        "any information disclosed by one party to the other, whether "
        "orally, in writing or in any other form, that is designated as "
        "confidential or that a reasonable person would understand to "
        "be confidential given its nature and the circumstances of "
        "disclosure"
    ),
    "Deliverables": (
        "any reports, documentation, code or other materials created or "
        "supplied by the Supplier for the Customer in the course of "
        "providing the Services"
    ),
    "Force Majeure Event": (
        "any event beyond the reasonable control of the affected party, "
        "including fire, flood, industrial action, failure of a utility "
        "service or an act of government, which prevents or delays that "
        "party from performing its obligations under this Agreement"
    ),
    "Intellectual Property Rights": (
        "patents, rights to inventions, copyright, trade marks, design "
        "rights, database rights and all other intellectual property "
        "rights, whether registered or unregistered, together with "
        "applications for any of the foregoing"
    ),
    "Personal Data": (
        "personal data, as that term is defined in the Data Protection "
        "Legislation, that is processed by the Supplier on behalf of "
        "the Customer in connection with the Services"
    ),
    "Services": (
        "the managed hosting, support and professional services "
        "described in Schedule 1"
    ),
    "Term": (
        "the period beginning on the Commencement Date and continuing "
        "until this Agreement is terminated in accordance with "
        "clause 11"
    ),
}

CROSS_REFERENCES = [
    ("clause 11", "11", "clause"),
    ("clause 2.2", "2.2", "clause"),
    ("Schedule 1", "Schedule 1", "schedule"),
    ("Schedule 2", "Schedule 2", "schedule"),
    ("clause 4.1", "4.1", "clause"),
    # Both paragraph references are to Schedule 2, though the first is
    # written from the main body ("... set out in paragraph 2 of Schedule 2").
    ("paragraph 2", "Schedule 2/2", "paragraph"),
    ("paragraph 3", "Schedule 2/3", "paragraph"),
    ("clause 6.1", "6.1", "clause"),
    ("clause 6", "6", "clause"),
    ("clause 8", "8", "clause"),
    ("clause 7.2", "7.2", "clause"),
    ("clause 10", "10", "clause"),
    ("clause 9.1", "9.1", "clause"),
    ("clause 9.2", "9.2", "clause"),
    ("clause 9", "9", "clause"),
    ("clause 9.3(b)", "9.3(b)", "clause"),
    ("clause 10.3", "10.3", "clause"),
    ("clause 1.1", "1.1", "clause"),
    ("clause 5.2", "5.2", "clause"),
]


# ---------------------------------------------------------------------------
# Second drafting pass
# ---------------------------------------------------------------------------
#
# Added to bring the fixture to the ~25 KB a real services agreement runs to,
# so the page furniture repeats often enough to matter and the parser has a
# document-sized amount of structure to get wrong.  Kept as a separate list
# rather than spliced into CLAUSES above so the two passes stay legible.
#
# Each addition is anchored to the clause it follows, named by (identifier,
# parent).  The identifier alone is not enough: "3" is a top-level clause,
# a paragraph of Schedule 1 and a paragraph of Schedule 2, and "(a)" occurs
# under several sub-clauses.  Anchors are applied in order, so an addition
# may anchor to one made before it.

_ADDITIONS: list[tuple[tuple[str, Optional[str]], Clause]] = [
    (('3.3', '3'), Clause(
        "3.4",
        "3.4 Audit Rights",
        1,
        "3",
        paragraphs=[
            "The Customer may, on giving the Supplier not less than "
            "fourteen days' written notice, audit the Supplier's "
            "compliance with its obligations under this Agreement, "
            "including by inspecting relevant records and processes at "
            "the Supplier's premises during normal business hours. The "
            "Supplier shall provide reasonable cooperation with any such "
            "audit, and neither party shall be entitled to conduct more "
            "than one audit under this clause 3.4 in any twelve month "
            "period, save where the Customer reasonably suspects a "
            "material breach of this Agreement.",
            "If an audit under this clause 3.4 identifies a material "
            "failure by the Supplier to comply with its obligations "
            "under this Agreement, the Supplier shall, at its own cost, "
            "remedy the failure within a reasonable time and shall "
            "reimburse the Customer's reasonable costs of the audit."
        ],
    )),
    (('3.4', '3'), Clause(
        "3.5",
        "3.5 Business Continuity and Disaster Recovery",
        1,
        "3",
        paragraphs=[
            "The Supplier shall maintain and test not less than annually "
            "a business continuity and disaster recovery plan designed "
            "to restore the Services within forty-eight hours of an "
            "unplanned outage, and shall provide the Customer with a "
            "written summary of the results of each test within thirty "
            "days of its completion. If the Supplier invokes its "
            "business continuity plan, it shall notify the Customer "
            "without delay and shall keep the Customer informed of "
            "progress towards restoration of the Services."
        ],
    )),
    (('4.3', '4'), Clause(
        "4.4",
        "4.4 Changes to Customer Requirements",
        1,
        "4",
        paragraphs=[
            "If the Customer requests a change to its requirements that "
            "materially increases the scope or cost of the Services, the "
            "Supplier shall notify the Customer of the resulting impact "
            "on the Charges and any applicable timescales before "
            "implementing the change. Neither party shall be obliged to "
            "proceed with a change requested under this clause 4.4 "
            "unless it is agreed in writing by both parties in "
            "accordance with the change control procedure described in "
            "Schedule 1."
        ],
    )),
    (('6.3', '6'), Clause(
        "6.4",
        "6.4 Compelled Disclosure",
        1,
        "6",
        paragraphs=[
            "If a party is required by law, regulation or a court or "
            "regulator of competent jurisdiction to disclose any "
            "Confidential Information of the other party, it shall, to "
            "the extent permitted by law, notify the other party "
            "promptly and cooperate with that party's reasonable "
            "requests in seeking to limit the scope of the disclosure or "
            "to obtain confidential treatment for the information "
            "disclosed."
        ],
    )),
    (('6.4', '6'), Clause(
        "6.5",
        "6.5 Publicity",
        1,
        "6",
        paragraphs=[
            "Neither party shall use the other party's name, logo or "
            "trade marks in any press release, marketing material or "
            "public announcement relating to this Agreement without the "
            "prior written consent of the other party, save as required "
            "by law or by any regulatory authority."
        ],
    )),
    (('7.3', '7'), Clause(
        "(a)",
        "(a) Notice of Engagement",
        3,
        "7.3",
        paragraphs=[
            "The Supplier shall give the Customer not less than thirty "
            "days' prior written notice before engaging any new "
            "sub-processor to process Personal Data, and the Customer "
            "may object to the proposed sub-processor on reasonable "
            "grounds relating to the protection of Personal Data within "
            "fourteen days of receiving that notice."
        ],
    )),
    (('(a)', '7.3'), Clause(
        "(b)",
        "(b) Sub-Processor Liability",
        3,
        "7.3",
        paragraphs=[
            "The Supplier remains fully liable to the Customer for the "
            "acts and omissions of any sub-processor engaged under this "
            "clause 7.3 as if they were the Supplier's own acts and "
            "omissions, and shall ensure that its written agreement with "
            "each sub-processor imposes obligations relating to Personal "
            "Data no less protective than those set out in clause 7.2."
        ],
    )),
    (('(b)', '7.3'), Clause(
        "7.4",
        "7.4 International Transfers",
        1,
        "7",
        paragraphs=[
            "The Supplier shall not transfer Personal Data outside the "
            "United Kingdom without the prior written consent of the "
            "Customer, and any such transfer shall be subject to "
            "appropriate safeguards recognised under the Data Protection "
            "Legislation, including standard contractual clauses or an "
            "adequacy decision covering the destination country. The "
            "Supplier shall notify the Customer promptly of any failure "
            "by a sub-processor to comply with the obligations imposed "
            "on it, as set out in clause 7.3(b)."
        ],
    )),
    (('(c)', '9.3'), Clause(
        "9.4",
        "9.4 Exclusions from Indemnities",
        1,
        "9",
        paragraphs=[
            "Neither party shall be liable to indemnify the other under "
            "clause 9.1 or clause 9.2 to the extent that the claim "
            "arises from the indemnified party's own negligence or "
            "breach of this Agreement, and the indemnities in this "
            "clause 9 are subject to the limitations and exclusions set "
            "out in clause 10.",
            "Any liability arising under an indemnity in clause 9.1 or "
            "clause 9.2 shall count towards, and not be in addition to, "
            "the financial cap in clause 10.2."
        ],
    )),
    (('11.4', '11'), Clause(
        "11.5",
        "11.5 Transitional Assistance",
        1,
        "11",
        paragraphs=[
            "On termination or expiry of this Agreement, the Supplier "
            "shall, for a period of up to ninety days at the Customer's "
            "request, provide reasonable assistance to transfer the "
            "Services to the Customer or a replacement supplier, and the "
            "Customer shall pay the Supplier's reasonable charges for "
            "such assistance at the Supplier's then-current standard "
            "rates."
        ],
    )),
    (('12.2', '12'), Clause("13", "13. Anti-Bribery and Compliance", 0, None)),
    (('13', None), Clause(
        "13.1",
        "13.1 Anti-Bribery",
        1,
        "13",
        paragraphs=[
            "Each party shall comply with all applicable anti-bribery "
            "and anti-corruption laws, including the Bribery Act 2010, "
            "and shall not offer, give, request or accept any bribe or "
            "other improper advantage in connection with this "
            "Agreement. The Supplier shall maintain adequate procedures "
            "designed to prevent bribery by persons associated with it, "
            "and shall promptly notify the Customer in writing if it "
            "becomes aware of any breach or suspected breach of this "
            "clause 13.1."
        ],
    )),
    (('13.1', '13'), Clause(
        "13.2",
        "13.2 Sanctions and Export Control",
        1,
        "13",
        paragraphs=[
            "Neither party shall be required to perform any obligation "
            "under this Agreement that would result in a breach of "
            "applicable trade sanctions or export control laws. Each "
            "party warrants that it is not, and shall notify the other "
            "party promptly if it becomes, a person designated under any "
            "applicable sanctions regime, and either party may suspend "
            "performance of the Services to the extent necessary to "
            "comply with its obligations under this clause 13.2."
        ],
    )),
    (('13.2', '13'), Clause(
        "13.3",
        "13.3 Compliance Training",
        1,
        "13",
        paragraphs=[
            "The Supplier shall ensure that its personnel who perform "
            "the Services receive appropriate training on the "
            "requirements of this clause 13 at intervals of not more "
            "than twelve months, and shall maintain records of that "
            "training available for inspection under clause 3.4."
        ],
    )),
    (('13.3', '13'), Clause("14", "14. Insurance", 0, None)),
    (('14', None), Clause(
        "14.1",
        "14.1 Insurance Obligations",
        1,
        "14",
        paragraphs=[
            "The Supplier shall maintain, at its own expense, "
            "professional indemnity insurance of not less than "
            "£2,000,000 in the aggregate, public liability insurance of "
            "not less than £5,000,000 in respect of any one occurrence, "
            "and cyber liability insurance of not less than £1,000,000 "
            "in the aggregate, in each case with a reputable insurer, "
            "for the duration of the Term and for a period of "
            "twenty-four months following its expiry or termination."
        ],
    )),
    (('14.1', '14'), Clause(
        "14.2",
        "14.2 Evidence of Insurance",
        1,
        "14",
        paragraphs=[
            "The Supplier shall, within ten Business Days of a written "
            "request from the Customer, provide evidence satisfactory to "
            "the Customer that the insurance required by clause 14.1 is "
            "in force, and shall notify the Customer promptly if any "
            "such insurance is cancelled, materially reduced or not "
            "renewed."
        ],
    )),
    (('14.2', '14'), Clause(
        "14.3",
        "14.3 Subrogation Waiver",
        1,
        "14",
        paragraphs=[
            "The Supplier shall use reasonable endeavours to procure "
            "that its insurers waive any right of subrogation against "
            "the Customer, except where the loss arises from the "
            "Customer's own wilful default or gross negligence."
        ],
    )),
    (('14.3', '14'), Clause("15", "15. Dispute Resolution and Escalation", 0, None)),
    (('15', None), Clause(
        "15.1",
        "15.1 Escalation Procedure",
        1,
        "15",
        paragraphs=[
            "If a dispute arises out of or in connection with this "
            "Agreement that is not resolved by the parties' respective "
            "account managers within ten Business Days, either party "
            "may refer the dispute in writing to a director of each "
            "party, who shall use reasonable endeavours to resolve the "
            "dispute within a further fifteen Business Days before "
            "either party commences formal proceedings, save that either "
            "party may seek urgent injunctive relief at any time without "
            "following this procedure."
        ],
    )),
    (('15.1', '15'), Clause(
        "15.2",
        "15.2 Mediation",
        1,
        "15",
        paragraphs=[
            "If a dispute referred under clause 15.1 remains unresolved "
            "after the escalation period has expired, the parties shall "
            "attempt in good faith to settle the dispute by mediation in "
            "accordance with the Centre for Effective Dispute Resolution "
            "Model Mediation Procedure before either party commences "
            "court proceedings, save that this clause 15.2 shall not "
            "prevent either party from applying to the courts referred "
            "to in clause 12.2 for interim relief."
        ],
    )),
    (('15.2', '15'), Clause(
        "15.3",
        "15.3 Continued Performance",
        1,
        "15",
        paragraphs=[
            "Each party shall continue to perform its obligations under "
            "this Agreement during the resolution of any dispute under "
            "clause 15.1 or clause 15.2, unless the parties agree "
            "otherwise in writing or the dispute is incapable of "
            "resolution without such performance ceasing."
        ],
    )),
    (('3', 'Schedule 1'), Clause(
        "4",
        "4. Reporting",
        0,
        "Schedule 1",
        paragraphs=[
            "The Supplier shall provide the Customer with a monthly "
            "service report setting out performance against the service "
            "levels described in this Schedule 1, including any "
            "incidents of downtime and the corrective action taken, no "
            "later than ten Business Days after the end of the month to "
            "which the report relates."
        ],
    )),
    (('4', 'Schedule 1'), Clause(
        "5",
        "5. Service Credits",
        0,
        "Schedule 1",
        paragraphs=[
            "If the Supplier fails to achieve the monthly uptime target "
            "described above in two consecutive months, the Supplier "
            "shall credit the Customer an amount equal to five per cent "
            "of the Charges payable for the second such month, such "
            "credit to be applied against the Customer's next invoice."
        ],
    )),
    (('3', 'Schedule 2'), Clause(
        "4",
        "4. Expenses",
        0,
        "Schedule 2",
        paragraphs=[
            "The Charges do not include travel, accommodation or other "
            "out-of-pocket expenses reasonably incurred by the Supplier "
            "in providing the Services, which shall be reimbursed by the "
            "Customer within thirty days of receipt of a valid invoice "
            "supported by appropriate receipts, provided that any single "
            "item of expenditure exceeding £250 shall require the "
            "Customer's prior written approval."
        ],
    )),
    (('4', 'Schedule 2'), Clause(
        "5",
        "5. Disputed Invoices",
        0,
        "Schedule 2",
        paragraphs=[
            "If the Customer disputes any part of an invoice in good "
            "faith, it shall notify the Supplier in writing of the "
            "disputed amount and the reasons for the dispute within "
            "fifteen Business Days of receipt of the invoice, and shall "
            "pay the undisputed balance by the due date. The parties "
            "shall use reasonable endeavours to resolve the dispute "
            "promptly, failing which either party may refer it in "
            "accordance with the procedure described in this Agreement."
        ],
    )),
]


def _apply_additions(
    base: list[Clause],
    additions: list[tuple[tuple[str, Optional[str]], Clause]],
) -> list[Clause]:
    """Splice each addition in directly after its anchor clause.

    Raises:
        ValueError: If an anchor matches no clause, or more than one — in
            which case the anchor is ambiguous and must be made specific.
    """
    merged = list(base)
    for (identifier, parent), clause in additions:
        matches = [
            index
            for index, candidate in enumerate(merged)
            if candidate.identifier == identifier and candidate.parent == parent
        ]
        if len(matches) != 1:
            raise ValueError(
                f"anchor {(identifier, parent)!r} matched {len(matches)} "
                f"clauses; it must match exactly one"
            )
        merged.insert(matches[0] + 1, clause)
    return merged


CLAUSES = _apply_additions(CLAUSES, _ADDITIONS)

# References declared by the second pass.  Several repeat a triple already
# declared above; emit() records every occurrence of a raw phrase once, so
# the list is de-duplicated rather than concatenated.
_ADDITIONAL_CROSS_REFERENCES = [
    ("clause 3.4", "3.4", "clause"),
    ("clause 4.4", "4.4", "clause"),
    ("Schedule 1", "Schedule 1", "schedule"),
    ("clause 7.3", "7.3", "clause"),
    ("clause 7.2", "7.2", "clause"),
    ("clause 7.3(b)", "7.3(b)", "clause"),
    ("clause 9.1", "9.1", "clause"),
    ("clause 9.2", "9.2", "clause"),
    ("clause 9", "9", "clause"),
    ("clause 10", "10", "clause"),
    ("clause 10.2", "10.2", "clause"),
    ("clause 13", "13", "clause"),
    ("clause 13.1", "13.1", "clause"),
    ("clause 13.2", "13.2", "clause"),
    ("clause 14.1", "14.1", "clause"),
    ("clause 15.1", "15.1", "clause"),
    ("clause 15.2", "15.2", "clause"),
    ("clause 12.2", "12.2", "clause"),
]

CROSS_REFERENCES = list(
    dict.fromkeys([*CROSS_REFERENCES, *_ADDITIONAL_CROSS_REFERENCES])
)

def main() -> None:
    text, gold = emit(
        name=NAME,
        preamble=PREAMBLE,
        clauses=CLAUSES,
        defined_terms=DEFINED_TERMS,
        cross_references=CROSS_REFERENCES,
        description=(
            "UK services agreement as extracted from a PDF: running "
            "headers and footers, 78-column hard wrapping, a "
            "soft-hyphenated word, definitions and schedules."
        ),
        page_lines=45,
        running_header="CONFIDENTIAL — Project Atlas Services Agreement",
        running_footer="Page {page} of {total}",
        soft_hyphens=[("indemnification", 9)],
        # Split a cross-reference between its label and its number.
        # Each half alone is meaningless, and the second half --
        # "7.3(b) ..." at the head of a line -- looks exactly like a
        # clause heading.
        line_breaks=[("as set out in clause 7.3(b)", "clause")],
    )
    write(NAME, text, gold)


if __name__ == "__main__":
    main()
