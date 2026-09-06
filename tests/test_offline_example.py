from examples.offline_evidence_retrieval import retrieve_evidence


def test_offline_evidence_retrieval_returns_clause_definition_and_offsets():
    evidence = retrieve_evidence("How may the Recipient use Confidential Information?")

    assert "2.1" in evidence["clause"]["hierarchy_path"]
    assert "shall use it only" in evidence["clause"]["source_text"]
    assert evidence["clause"]["source_offsets"][0] < evidence["clause"]["source_offsets"][1]
    assert evidence["definitions"][0]["term"] == "Confidential Information"
    assert "non-public commercial or technical information" in evidence["definitions"][0]["definition"]
    assert '"Confidential Information" means' in evidence["definitions"][0]["source_text"]
    assert evidence["definitions"][0]["source_offsets"][0] < evidence["definitions"][0]["source_offsets"][1]
