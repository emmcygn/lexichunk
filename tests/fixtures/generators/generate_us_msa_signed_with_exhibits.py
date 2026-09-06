"""Generate tests/fixtures/us_msa_signed_with_exhibits.txt and its gold annotation.

A fully executed US master services agreement: WHEREAS recitals, nine
ARTICLEs whose titles sit on a second heading line, lettered sub-clauses, an
IN WITNESS WHEREOF execution block with two signature stacks, and two
statement-of-work exhibits *after* the signatures.

Two traps are deliberate. The word "execution" and the phrase "survive
execution" appear in operative clauses well before the real signature block,
so a document-section classifier that searches for the word rather than the
formula mislabels them. And the exhibits come after the execution block, so
anything that treats the signatures as the end of the document loses them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _emit import Clause, emit, write

NAME = "us_msa_signed_with_exhibits"
DESCRIPTION = (
    "A fully executed nine-article US master services agreement between a "
    "Delaware provider and a New York customer, with lettered sub-clauses, "
    "a signature block, and two statement-of-work exhibits."
)

PREAMBLE: list[str] = [
    "MASTER SERVICES AGREEMENT",
    'This Master Services Agreement (this "Agreement") is entered into as of '
    'March 3, 2025 (the "Effective Date") by and between Solstice Cloud '
    "Systems, Inc., a Delaware corporation with its principal place of "
    'business at 1180 Marina Village Parkway, Suite 300, Alameda, California '
    '94501 ("Provider"), and Brightwell Retail Holdings, LLC, a New York '
    "limited liability company with its principal place of business at 450 "
    'West 33rd Street, New York, New York 10001 ("Customer"). Provider and '
    'Customer are each referred to individually as a "Party" and '
    'collectively as the "Parties."',
    "WHEREAS, Provider owns and operates a cloud-based inventory "
    "optimization and supply chain analytics platform and provides related "
    "implementation, integration, and support services to enterprise "
    "customers;",
    "WHEREAS, Customer operates a nationwide chain of retail stores and "
    "distribution centers and desires to engage Provider to implement and "
    "support that platform in connection with Customer's supply chain "
    "operations;",
    "WHEREAS, the parties previously conducted a limited pilot engagement "
    "under a letter of intent dated November 12, 2024, the results of which "
    "the parties wish to memorialize and expand upon under the terms of a "
    "definitive, comprehensive agreement;",
    "WHEREAS, Provider is willing to provide the Services described in "
    "this Agreement, and Customer is willing to pay the Fees for the "
    "Services, in each case on the terms and subject to the conditions set "
    "forth in this Agreement;",
    "NOW, THEREFORE, in consideration of the mutual covenants and "
    "agreements set forth in this Agreement, and for other good and "
    "valuable consideration, the receipt and sufficiency of which are "
    "hereby acknowledged, the parties agree as follows:",
]

CLAUSES: list[Clause] = [
    # ------------------------------------------------------------------
    # ARTICLE I
    # ------------------------------------------------------------------
    Clause(
        "Article I",
        "ARTICLE I",
        0,
        None,
        subtitle="DEFINITIONS AND INTERPRETATION",
    ),
    Clause(
        "Section 1.01",
        "Section 1.01 Definitions.",
        1,
        "Article I",
        paragraphs=[
            "As used in this Agreement, the following terms have the "
            "meanings set forth below.",
            '"Affiliate" means any other entity that directly or '
            "indirectly controls, is controlled by, or is under common "
            "control with a Person, where control means the ownership of "
            "more than fifty percent (50%) of the outstanding voting "
            "securities of an entity or the contractual power to direct "
            "its management and policies.",
            '"Authorized User" means an employee, contractor, or agent of '
            "Customer who is authorized by Customer to access and use the "
            "Services in accordance with this Agreement and an applicable "
            "Order Form, and who has agreed to comply with an acceptable "
            "use policy no less restrictive than the terms of this "
            "Agreement.",
            '"Confidential Information" means any information disclosed '
            'by one party (the "Disclosing Party") to the other party '
            '(the "Receiving Party"), whether disclosed orally, in '
            "writing, or in any other form, that is marked as "
            "confidential at the time of disclosure or that a reasonable "
            "person would understand to be confidential given the "
            "circumstances of disclosure.",
            '"Deliverables" means the reports, software, documentation, '
            "data models, and other work product that Provider is "
            "expressly required to deliver to Customer under an Order "
            "Form, as identified in that Order Form as a deliverable.",
            '"Documentation" means the user guides, administrator guides, '
            "application programming interface specifications, and other "
            "technical materials that Provider makes generally available "
            "to its customers describing the use and operation of the "
            "Services, as updated by Provider from time to time.",
            '"Fees" means the amounts payable by Customer to Provider for '
            "the Services as set forth in an Order Form, including any "
            "implementation fees, subscription fees, usage-based fees, "
            "and professional services fees.",
            '"Intellectual Property Rights" means all patents, '
            "copyrights, trademarks, trade secrets, moral rights, and any "
            "other intellectual property or proprietary rights recognized "
            "in any jurisdiction, together with all applications, "
            "registrations, and renewals of the foregoing.",
            '"Order Form" means a written or electronic ordering '
            "document, statement of work, or similar document executed by "
            "both parties that references this Agreement, describes the "
            "Services to be provided, and sets forth the applicable Fees, "
            "and that upon execution is incorporated into and governed by "
            "this Agreement.",
            '"Services" means the software subscription, implementation, '
            "integration, and support services described in an Order "
            "Form or in Exhibit A or Exhibit B attached to this "
            "Agreement, together with any related Deliverables.",
            '"Term" means the period commencing on the Effective Date and '
            "continuing until this Agreement is terminated in accordance "
            "with Article IV.",
        ],
    ),
    Clause(
        "Section 1.02",
        "Section 1.02 Interpretation.",
        1,
        "Article I",
        paragraphs=[
            "In this Agreement, unless the context otherwise requires: "
            "words importing the singular include the plural and vice "
            'versa; the words "include," "includes," and "including" are '
            'deemed followed by the phrase "without limitation"; a '
            "reference to any statute includes any amendment or "
            "replacement of it; and headings are for convenience only "
            "and do not affect interpretation.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE II
    # ------------------------------------------------------------------
    Clause(
        "Article II",
        "ARTICLE II",
        0,
        None,
        subtitle="SCOPE OF SERVICES",
    ),
    Clause(
        "Section 2.01",
        "Section 2.01 Provision of Services.",
        1,
        "Article II",
        paragraphs=[
            "Provider shall provide the Services to Customer in "
            "accordance with this Agreement and each applicable Order "
            "Form, in a professional and workmanlike manner consistent "
            "with prevailing industry standards, and shall devote "
            "qualified personnel sufficient to meet the timelines set "
            "forth in the applicable Order Form.",
        ],
    ),
    Clause(
        "Section 2.02",
        "Section 2.02 Statements of Work and Order Forms.",
        1,
        "Article II",
        paragraphs=[
            "The parties may from time to time enter into additional "
            "Order Forms describing specific deliverables, milestones, "
            "staffing, and acceptance criteria for a particular "
            "engagement. Each Order Form is subject to this Agreement, "
            "and the terms of this Agreement control over an Order Form "
            "unless the Order Form expressly states that it supersedes a "
            "specifically identified provision of this Agreement.",
        ],
    ),
    Clause(
        "Section 2.03",
        "Section 2.03 Change Orders.",
        1,
        "Article II",
        paragraphs=[
            "Either party may propose a change to the scope, timeline, or "
            "fees of an Order Form by written change request. No change "
            "is binding unless documented in a written change order "
            "signed by an authorized representative of each party, and "
            "Provider is not obligated to perform any change until the "
            "change order has been fully executed.",
        ],
    ),
    Clause(
        "Section 2.04",
        "Section 2.04 Customer Responsibilities.",
        1,
        "Article II",
        paragraphs=[
            "Customer shall, at its own cost and expense, satisfy each of "
            "the following obligations throughout the Term:",
        ],
    ),
    Clause(
        "(a)",
        "(a) Access and Cooperation.",
        3,
        "Section 2.04",
        paragraphs=[
            "Customer shall provide Provider with timely access to "
            "Customer's systems, facilities, data, and personnel as "
            "reasonably necessary for Provider to perform the Services, "
            "and shall respond to Provider's requests for information or "
            "decisions within five (5) business days.",
        ],
    ),
    Clause(
        "(b)",
        "(b) Project Governance.",
        3,
        "Section 2.04",
        paragraphs=[
            "Customer shall designate a project manager who has "
            "authority to make decisions and grant approvals on "
            "Customer's behalf, and shall promptly notify Provider in "
            "writing of any change to that designation.",
        ],
    ),
    Clause(
        "(c)",
        "(c) Accuracy of Information.",
        3,
        "Section 2.04",
        paragraphs=[
            "Customer shall ensure that all data, specifications, and "
            "other information it provides to Provider are accurate and "
            "complete in all material respects, and Provider shall have "
            "no liability for any deficiency in the Services to the "
            "extent caused by Customer's failure to satisfy its "
            "obligations under this Section 2.04.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE III
    # ------------------------------------------------------------------
    Clause(
        "Article III",
        "ARTICLE III",
        0,
        None,
        subtitle="FEES AND PAYMENT",
    ),
    Clause(
        "Section 3.01",
        "Section 3.01 Fees.",
        1,
        "Article III",
        paragraphs=[
            "Customer shall pay Provider the Fees set forth in each Order "
            "Form. Except as otherwise expressly stated in an Order Form, "
            "all Fees are quoted and payable in United States dollars, "
            "are exclusive of taxes, and are non-refundable and "
            "non-creditable once invoiced.",
        ],
    ),
    Clause(
        "Section 3.02",
        "Section 3.02 Invoicing and Payment.",
        1,
        "Article III",
        paragraphs=[
            "Provider shall invoice Customer monthly in arrears for Fees "
            "accrued during the preceding month, or on such other "
            "schedule as set forth in the applicable Order Form. "
            'Customer shall pay each undisputed invoice within thirty '
            '(30) days after the invoice date (the "Payment Due Date") '
            "by wire transfer or ACH, and may withhold any amount it "
            "disputes in good faith by notifying Provider in writing "
            "within fifteen (15) days after the invoice date.",
        ],
    ),
    Clause(
        "Section 3.03",
        "Section 3.03 Late Payments.",
        1,
        "Article III",
        paragraphs=[
            "Any amount not paid by the Payment Due Date accrues "
            "interest at the rate of one and one-half percent (1.5%) per "
            "month, or the highest rate permitted by law, whichever is "
            "lower, from the Payment Due Date until paid in full. If any "
            "undisputed invoice remains unpaid more than thirty (30) "
            "days after written notice, Provider may suspend the "
            "Services described in Section 3.01 until payment is "
            "received.",
        ],
    ),
    Clause(
        "Section 3.04",
        "Section 3.04 Taxes.",
        1,
        "Article III",
        paragraphs=[
            'The Fees do not include sales, use, value-added, or similar '
            'taxes (collectively, "Taxes"), and Customer is responsible '
            "for all Taxes associated with its purchases, other than "
            "taxes on Provider's net income. If Customer is required by "
            "law to withhold Taxes from a payment, Customer shall gross "
            "up the payment so Provider receives the full amount it "
            "would have received absent the withholding.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE IV
    # ------------------------------------------------------------------
    Clause(
        "Article IV",
        "ARTICLE IV",
        0,
        None,
        subtitle="TERM AND TERMINATION",
    ),
    Clause(
        "Section 4.01",
        "Section 4.01 Term.",
        1,
        "Article IV",
        paragraphs=[
            "This Agreement commences on the Effective Date and continues "
            "until terminated as provided in this Article IV. The "
            "initial term of each Order Form is set forth therein, and "
            "each Order Form renews automatically for successive one-year "
            "terms unless either party gives the other written notice of "
            "non-renewal at least sixty (60) days before the end of the "
            "then-current term.",
        ],
    ),
    Clause(
        "Section 4.02",
        "Section 4.02 Termination for Convenience.",
        1,
        "Article IV",
        paragraphs=[
            "Either party may terminate this Agreement for convenience "
            "by giving the other party at least ninety (90) days' prior "
            "written notice; provided that such termination does not "
            "affect any Order Form then in effect, which continues to be "
            "governed by this Agreement through its stated expiration or "
            "earlier termination in accordance with Section 4.03.",
        ],
    ),
    Clause(
        "Section 4.03",
        "Section 4.03 Termination for Cause.",
        1,
        "Article IV",
        paragraphs=[
            "Either party may terminate this Agreement or any Order Form "
            "immediately upon written notice to the other party under any "
            "of the following circumstances:",
        ],
    ),
    Clause(
        "(a)",
        "(a) Uncured Material Breach.",
        3,
        "Section 4.03",
        paragraphs=[
            "The other party materially breaches this Agreement or an "
            "Order Form and fails to cure the breach within thirty (30) "
            "days after receiving written notice describing the breach "
            "in reasonable detail.",
        ],
    ),
    Clause(
        "(b)",
        "(b) Insolvency.",
        3,
        "Section 4.03",
        paragraphs=[
            "The other party becomes insolvent, makes an assignment for "
            "the benefit of creditors, or becomes subject to a bankruptcy "
            "or insolvency proceeding that is not dismissed within sixty "
            "(60) days of its filing.",
        ],
    ),
    Clause(
        "(c)",
        "(c) Cessation of Business.",
        3,
        "Section 4.03",
        paragraphs=[
            "The other party ceases to conduct business in the ordinary "
            "course for a period of more than thirty (30) consecutive "
            "days.",
        ],
    ),
    Clause(
        "Section 4.04",
        "Section 4.04 Effect of Termination.",
        1,
        "Article IV",
        paragraphs=[
            "Upon termination of this Agreement, Customer shall pay all "
            "Fees accrued through the termination date, and each party "
            "shall return the other party's Confidential Information in "
            "accordance with Article V. Licenses under Article VI for "
            "terminated Services immediately terminate, and Article I, "
            "Article III (as to Fees accrued before termination), "
            "Article V, Article VI, Article VII, Article VIII, and "
            "Article IX shall survive termination.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE V
    # ------------------------------------------------------------------
    Clause(
        "Article V",
        "ARTICLE V",
        0,
        None,
        subtitle="CONFIDENTIALITY",
    ),
    Clause(
        "Section 5.01",
        "Section 5.01 Confidentiality Obligations.",
        1,
        "Article V",
        paragraphs=[
            "Each party shall hold the other party's Confidential "
            "Information in confidence using at least the degree of "
            "care it uses to protect its own confidential information, "
            "but not less than reasonable care; shall not disclose it "
            "to any third party except as permitted under Section 5.02; "
            "and shall use it solely to perform its obligations under "
            "this Agreement.",
        ],
    ),
    Clause(
        "Section 5.02",
        "Section 5.02 Permitted Disclosures.",
        1,
        "Article V",
        paragraphs=[
            "A party may disclose the other party's Confidential "
            "Information to its employees, Affiliates, contractors, and "
            "professional advisors who need to know it and who are bound "
            "by confidentiality obligations at least as protective as "
            "those in this Article V, and may disclose it to the extent "
            "required by applicable law or a valid court order, provided "
            "that, where legally permitted, it gives the disclosing "
            "party prompt written notice.",
        ],
    ),
    Clause(
        "Section 5.03",
        "Section 5.03 Survival.",
        1,
        "Article V",
        paragraphs=[
            "The obligations in this Article V shall survive execution "
            "and any termination of this Agreement for a period of five "
            "(5) years, except that obligations relating to Confidential "
            "Information that constitutes a trade secret under applicable "
            "law shall continue for as long as that information remains "
            "a trade secret.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE VI
    # ------------------------------------------------------------------
    Clause(
        "Article VI",
        "ARTICLE VI",
        0,
        None,
        subtitle="INTELLECTUAL PROPERTY",
    ),
    Clause(
        "Section 6.01",
        "Section 6.01 Provider Ownership.",
        1,
        "Article VI",
        paragraphs=[
            "As between the parties, Provider owns all right, title, and "
            "interest in and to the Services, the Documentation, and all "
            "other technology, tools, and know-how that Provider uses in "
            "providing the Services, including all Intellectual Property "
            "Rights therein. Except for the rights expressly granted in "
            "this Agreement, no license or other right in the foregoing "
            "is granted to Customer.",
        ],
    ),
    Clause(
        "Section 6.02",
        "Section 6.02 License Grant.",
        1,
        "Article VI",
        paragraphs=[
            "Subject to Customer's compliance with this Agreement and "
            "timely payment of all Fees, Provider grants Customer a "
            "non-exclusive, non-transferable, non-sublicensable license "
            "during the term of the applicable Order Form to access and "
            "use the Services and Documentation solely for Customer's "
            "internal business purposes.",
        ],
    ),
    Clause(
        "Section 6.03",
        "Section 6.03 Customer Data.",
        1,
        "Article VI",
        paragraphs=[
            "As between the parties, Customer owns all right, title, and "
            'interest in the data that Customer submits to the Services '
            '("Customer Data"). Customer grants Provider a '
            "non-exclusive, worldwide license to host, process, "
            "transmit, and display Customer Data solely to provide the "
            "Services. Provider shall not use Customer Data to train "
            "any model for the benefit of any other customer without "
            "Customer's prior written consent.",
        ],
    ),
    Clause(
        "Section 6.04",
        "Section 6.04 Deliverables.",
        1,
        "Article VI",
        paragraphs=[
            "Unless an Order Form states otherwise, Deliverables that "
            "Provider develops specifically for Customer under an Order "
            "Form, excluding pre-existing Provider technology "
            "incorporated into them, are works made for hire owned by "
            "Customer upon full payment of the associated Fees; if a "
            "Deliverable does not qualify as a work made for hire, "
            "Provider assigns it to Customer upon that payment.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE VII
    # ------------------------------------------------------------------
    Clause(
        "Article VII",
        "ARTICLE VII",
        0,
        None,
        subtitle="REPRESENTATIONS AND WARRANTIES",
    ),
    Clause(
        "Section 7.01",
        "Section 7.01 Mutual Representations.",
        1,
        "Article VII",
        paragraphs=[
            "Each party represents and warrants that it has the full "
            "corporate power and authority to enter into this Agreement "
            "and that this Agreement constitutes its legal, valid, and "
            "binding obligation, enforceable against it in accordance "
            "with its terms.",
        ],
    ),
    Clause(
        "Section 7.02",
        "Section 7.02 Provider Warranty.",
        1,
        "Article VII",
        paragraphs=[
            "Provider warrants that the Services will perform materially "
            "in accordance with the applicable Documentation. Customer's "
            "sole remedy, and Provider's entire liability, for breach of "
            "this Section 7.02 is for Provider to use commercially "
            "reasonable efforts to correct the non-conforming Services "
            "or, failing that within sixty (60) days, to refund the "
            "Fees paid for the affected Services.",
        ],
    ),
    Clause(
        "Section 7.03",
        "Section 7.03 Disclaimer.",
        1,
        "Article VII",
        paragraphs=[
            'EXCEPT AS EXPRESSLY SET FORTH IN SECTION 7.02, THE SERVICES '
            'AND DELIVERABLES ARE PROVIDED "AS IS," AND PROVIDER '
            "DISCLAIMS ALL OTHER WARRANTIES, WHETHER EXPRESS, IMPLIED, OR "
            "STATUTORY, INCLUDING ANY IMPLIED WARRANTY OF "
            "MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, "
            "AND NON-INFRINGEMENT, AND ANY WARRANTY ARISING FROM COURSE "
            "OF DEALING OR USAGE OF TRADE.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE VIII
    # ------------------------------------------------------------------
    Clause(
        "Article VIII",
        "ARTICLE VIII",
        0,
        None,
        subtitle="INDEMNIFICATION AND LIMITATION OF LIABILITY",
    ),
    Clause(
        "Section 8.01",
        "Section 8.01 Indemnification by Provider.",
        1,
        "Article VIII",
        paragraphs=[
            "Provider shall defend, indemnify, and hold harmless Customer "
            'and its officers, directors, and employees (collectively, '
            '"Customer Indemnitees") from any third-party claim, and '
            "shall pay any resulting damages, costs, and reasonable "
            'attorneys\' fees (collectively, "Losses"), to the extent '
            "arising from an allegation that the Services, as used in "
            "accordance with this Agreement, infringe a third party's "
            "Intellectual Property Rights.",
        ],
    ),
    Clause(
        "Section 8.02",
        "Section 8.02 Indemnification by Customer.",
        1,
        "Article VIII",
        paragraphs=[
            "Customer shall defend, indemnify, and hold harmless Provider "
            'and its officers, directors, and employees (collectively, '
            '"Provider Indemnitees") from any Losses arising from '
            "Customer's breach of Article V, from Customer Data "
            "infringing a third party's rights, or from Customer's use "
            "of the Services in violation of applicable law.",
        ],
    ),
    Clause(
        "Section 8.03",
        "Section 8.03 Indemnification Procedure.",
        1,
        "Article VIII",
        paragraphs=[
            "The party seeking indemnification under Section 8.01 or "
            'Section 8.02 (the "Indemnified Party") shall satisfy each of '
            "the following conditions as a precondition to "
            "indemnification:",
        ],
    ),
    Clause(
        "(a)",
        "(a) Notification.",
        3,
        "Section 8.03",
        paragraphs=[
            "The Indemnified Party shall promptly notify the party from "
            'whom indemnification is sought (the "Indemnifying Party") in '
            "writing of the claim, provided that a delay in notice "
            "relieves the Indemnifying Party of its obligations under "
            "this Section 8.03 only to the extent the delay materially "
            "prejudices its defense.",
        ],
    ),
    Clause(
        "(b)",
        "(b) Control of Defense.",
        3,
        "Section 8.03",
        paragraphs=[
            "The Indemnified Party shall give the Indemnifying Party sole "
            "control of the defense and settlement of the claim, except "
            "that the Indemnifying Party may not settle any claim in a "
            "manner that admits fault by, or imposes any obligation on, "
            "the Indemnified Party without the Indemnified Party's prior "
            "written consent.",
        ],
    ),
    Clause(
        "(c)",
        "(c) Cooperation.",
        3,
        "Section 8.03",
        paragraphs=[
            "The Indemnified Party shall provide reasonable cooperation "
            "to the Indemnifying Party, at the Indemnifying Party's "
            "expense, and may participate in the defense with its own "
            "counsel at its own expense.",
        ],
    ),
    Clause(
        "Section 8.04",
        "Section 8.04 Limitation of Liability.",
        1,
        "Article VIII",
        paragraphs=[
            "EXCEPT FOR LOSSES ARISING FROM A PARTY'S INDEMNIFICATION "
            "OBLIGATIONS UNDER SECTION 8.01 OR SECTION 8.02, A BREACH OF "
            "ARTICLE V, OR A PARTY'S GROSS NEGLIGENCE OR WILLFUL "
            "MISCONDUCT, NEITHER PARTY SHALL BE LIABLE TO THE OTHER FOR "
            "ANY INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL "
            "DAMAGES, AND EACH PARTY'S TOTAL LIABILITY SHALL NOT EXCEED "
            "THE FEES PAID BY CUSTOMER DURING THE TWELVE (12) MONTHS "
            "PRECEDING THE CLAIM.",
        ],
    ),
    # ------------------------------------------------------------------
    # ARTICLE IX
    # ------------------------------------------------------------------
    Clause(
        "Article IX",
        "ARTICLE IX",
        0,
        None,
        subtitle="GENERAL PROVISIONS",
    ),
    Clause(
        "Section 9.01",
        "Section 9.01 Governing Law; Venue.",
        1,
        "Article IX",
        paragraphs=[
            "This Agreement is governed by the laws of the State of "
            "Delaware, without regard to its conflict of laws principles. "
            "Each party irrevocably submits to the exclusive jurisdiction "
            "of the state and federal courts located in the Borough of "
            "Manhattan, City and State of New York, for any action "
            "arising out of or relating to this Agreement, and waives any "
            "objection to venue in those courts.",
        ],
    ),
    Clause(
        "Section 9.02",
        "Section 9.02 Notices.",
        1,
        "Article IX",
        paragraphs=[
            "All notices under this Agreement shall be in writing and "
            "addressed to the applicable party at the address set forth "
            "on the signature page, or such other address as that party "
            "designates by notice given in accordance with this Section "
            "9.02, and shall be deemed given as follows:",
        ],
    ),
    Clause(
        "(a)",
        "(a) Personal Delivery.",
        3,
        "Section 9.02",
        paragraphs=[
            "A notice delivered by hand is deemed given upon delivery.",
        ],
    ),
    Clause(
        "(b)",
        "(b) Courier.",
        3,
        "Section 9.02",
        paragraphs=[
            "A notice sent by a nationally recognized overnight courier, "
            "freight prepaid, is deemed given one (1) business day after "
            "deposit with the courier.",
        ],
    ),
    Clause(
        "(c)",
        "(c) Mail.",
        3,
        "Section 9.02",
        paragraphs=[
            "A notice sent by United States mail, postage prepaid, "
            "certified or registered, return receipt requested, is "
            "deemed given three (3) business days after deposit in the "
            "mail.",
        ],
    ),
    Clause(
        "Section 9.03",
        "Section 9.03 Assignment.",
        1,
        "Article IX",
        paragraphs=[
            "Neither party may assign this Agreement without the prior "
            "written consent of the other party, which consent shall not "
            "be unreasonably withheld, except that either party may "
            "assign this Agreement without consent to an Affiliate or to "
            "a successor in a merger, acquisition, or sale of "
            "substantially all of its assets, provided the assignee "
            "agrees in writing to be bound by this Agreement.",
        ],
    ),
    Clause(
        "Section 9.04",
        "Section 9.04 Entire Agreement; Amendment.",
        1,
        "Article IX",
        paragraphs=[
            "This Agreement, together with all Order Forms and Exhibits "
            "incorporated by reference, constitutes the entire agreement "
            "between the parties and supersedes all prior agreements, "
            "proposals, and understandings, whether oral or written. No "
            "amendment is effective unless in writing and signed by an "
            "authorized representative of each party, and this Agreement "
            "may be executed in counterparts, including by electronic "
            "signature.",
        ],
    ),
    # ------------------------------------------------------------------
    # EXECUTION BLOCK
    # ------------------------------------------------------------------
    Clause(
        "IN WITNESS WHEREOF",
        "IN WITNESS WHEREOF",
        0,
        None,
        paragraphs=[
            "IN WITNESS WHEREOF, the parties have caused this Agreement "
            "to be executed by their duly authorized representatives as "
            "of the Effective Date.",
            "SOLSTICE CLOUD SYSTEMS, INC.",
            "By:",
            "Name:",
            "Title:",
            "Date:",
            "BRIGHTWELL RETAIL HOLDINGS, LLC",
            "By:",
            "Name:",
            "Title:",
            "Date:",
        ],
    ),
    # ------------------------------------------------------------------
    # EXHIBIT A
    # ------------------------------------------------------------------
    Clause(
        "Exhibit A",
        "EXHIBIT A",
        -2,
        None,
        subtitle="STATEMENT OF WORK NO. 1",
    ),
    Clause(
        "1.",
        "1. Description of Services",
        0,
        "Exhibit A",
        paragraphs=[
            "Provider shall implement its Inventory Optimization "
            'Platform (the "Platform") for up to two hundred (200) '
            "Authorized Users across Customer's distribution centers, "
            "including demand-forecasting model configuration, "
            "integration with Customer's warehouse management system, "
            "and migration of twenty-four (24) months of historical "
            "inventory data.",
            "Provider shall also deliver up to forty (40) hours of "
            "administrator training and a dedicated implementation "
            "manager for the engagement described in this Exhibit A.",
        ],
    ),
    Clause(
        "2.",
        "2. Deliverables and Milestones",
        0,
        "Exhibit A",
        paragraphs=[
            "The following milestones apply to the Services under this "
            "Exhibit A: Milestone 1, environment provisioning and data "
            "mapping, due thirty (30) days after the SOW Effective Date; "
            "Milestone 2, integration testing, due seventy-five (75) "
            "days after the SOW Effective Date; and Milestone 3, "
            "production go-live, due one hundred twenty (120) days "
            "after the SOW Effective Date. Provider shall notify "
            "Customer in writing upon completion of each milestone.",
        ],
    ),
    Clause(
        "3.",
        "3. Fees",
        0,
        "Exhibit A",
        paragraphs=[
            "The total fixed fee for the Services described in this "
            "Exhibit A is USD $312,000, payable as follows: USD $93,600 "
            "upon execution of this Exhibit A; USD $109,200 upon "
            "completion of Milestone 2; and USD $109,200 upon completion "
            "of Milestone 3. Fees under this Exhibit A are in addition to "
            "the ongoing subscription Fees set forth in Exhibit B and are "
            "invoiced in accordance with Section 3.02.",
        ],
    ),
    # ------------------------------------------------------------------
    # EXHIBIT B
    # ------------------------------------------------------------------
    Clause(
        "Exhibit B",
        "EXHIBIT B",
        -2,
        None,
        subtitle="SUBSCRIPTION SERVICES AND SERVICE LEVELS",
    ),
    Clause(
        "1.",
        "1. Subscription Services",
        0,
        "Exhibit B",
        paragraphs=[
            "Commencing on the go-live date confirmed under Exhibit A, "
            "Provider shall make the Platform available to Customer on a "
            "subscription basis for an initial term of thirty-six (36) "
            "months. The annual subscription fee is USD $180,000, payable "
            "annually in advance in accordance with Section 3.02, and "
            "includes standard support during Provider's business hours "
            "of 8:00 a.m. to 8:00 p.m. Eastern Time, Monday through "
            "Friday.",
        ],
    ),
    Clause(
        "2.",
        "2. Service Levels",
        0,
        "Exhibit B",
        paragraphs=[
            "Provider shall use commercially reasonable efforts to "
            "maintain a monthly Platform uptime of at least 99.5%, "
            "measured by Provider's monitoring tools and excluding "
            "scheduled maintenance of which Provider gives forty-eight "
            "(48) hours' prior notice. If uptime falls below target in "
            "a given month, Customer's sole remedy is a service credit "
            "of five percent (5%) of that month's fee per percentage "
            "point of shortfall, capped at twenty-five percent (25%).",
        ],
    ),
    Clause(
        "3.",
        "3. Renewal and Termination",
        0,
        "Exhibit B",
        paragraphs=[
            "The subscription described in this Exhibit B renews "
            "automatically for successive twelve-month terms unless "
            "either party provides notice of non-renewal in accordance "
            "with Section 4.01, and termination of this Exhibit B for "
            "Customer's uncured breach is governed by Section 4.03.",
        ],
    ),
]

DEFINED_TERMS: dict[str, str] = {
    "Affiliate": (
        "any other entity that directly or indirectly controls, is "
        "controlled by, or is under common control with a Person, where "
        "control means the ownership of more than fifty percent (50%) of "
        "the outstanding voting securities of an entity or the "
        "contractual power to direct its management and policies."
    ),
    "Authorized User": (
        "an employee, contractor, or agent of Customer who is authorized "
        "by Customer to access and use the Services in accordance with "
        "this Agreement and an applicable Order Form, and who has agreed "
        "to comply with an acceptable use policy no less restrictive "
        "than the terms of this Agreement."
    ),
    "Confidential Information": (
        'any information disclosed by one party (the "Disclosing '
        'Party") to the other party (the "Receiving Party"), whether '
        "disclosed orally, in writing, or in any other form, that is "
        "marked as confidential at the time of disclosure or that a "
        "reasonable person would understand to be confidential given "
        "the circumstances of disclosure."
    ),
    "Deliverables": (
        "the reports, software, documentation, data models, and other "
        "work product that Provider is expressly required to deliver to "
        "Customer under an Order Form, as identified in that Order Form "
        "as a deliverable."
    ),
    "Documentation": (
        "the user guides, administrator guides, application programming "
        "interface specifications, and other technical materials that "
        "Provider makes generally available to its customers describing "
        "the use and operation of the Services, as updated by Provider "
        "from time to time."
    ),
    "Fees": (
        "the amounts payable by Customer to Provider for the Services as "
        "set forth in an Order Form, including any implementation fees, "
        "subscription fees, usage-based fees, and professional services "
        "fees."
    ),
    "Intellectual Property Rights": (
        "all patents, copyrights, trademarks, trade secrets, moral "
        "rights, and any other intellectual property or proprietary "
        "rights recognized in any jurisdiction, together with all "
        "applications, registrations, and renewals of the foregoing."
    ),
    "Order Form": (
        "a written or electronic ordering document, statement of work, "
        "or similar document executed by both parties that references "
        "this Agreement, describes the Services to be provided, and "
        "sets forth the applicable Fees, and that upon execution is "
        "incorporated into and governed by this Agreement."
    ),
    "Services": (
        "the software subscription, implementation, integration, and "
        "support services described in an Order Form or in Exhibit A or "
        "Exhibit B attached to this Agreement, together with any "
        "related Deliverables."
    ),
    "Term": (
        "the period commencing on the Effective Date and continuing "
        "until this Agreement is terminated in accordance with "
        "Article IV."
    ),
}

CROSS_REFERENCES: list[tuple[str, str, str]] = [
    ("Exhibit A", "Exhibit A", "exhibit"),
    ("Exhibit B", "Exhibit B", "exhibit"),
    ("Article I", "Article I", "article"),
    ("Article III", "Article III", "article"),
    ("Article IV", "Article IV", "article"),
    ("Article V", "Article V", "article"),
    ("Article VI", "Article VI", "article"),
    ("Article VII", "Article VII", "article"),
    ("Article VIII", "Article VIII", "article"),
    ("Article IX", "Article IX", "article"),
    ("Section 2.04", "Section 2.04", "section"),
    ("Section 3.01", "Section 3.01", "section"),
    ("Section 3.02", "Section 3.02", "section"),
    ("Section 4.01", "Section 4.01", "section"),
    ("Section 4.03", "Section 4.03", "section"),
    ("Section 5.02", "Section 5.02", "section"),
    ("Section 7.02", "Section 7.02", "section"),
    ("Section 8.01", "Section 8.01", "section"),
    ("Section 8.02", "Section 8.02", "section"),
    ("Section 8.03", "Section 8.03", "section"),
    ("Section 9.02", "Section 9.02", "section"),
]


def main() -> None:
    text, gold = emit(
        name=NAME,
        preamble=PREAMBLE,
        clauses=CLAUSES,
        defined_terms=DEFINED_TERMS,
        cross_references=CROSS_REFERENCES,
        description=DESCRIPTION,
    )
    write(NAME, text, gold)


if __name__ == "__main__":
    main()
