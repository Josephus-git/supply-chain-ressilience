"""Risk Assessment pipeline (plain async generator in assess.py, no LangGraph):
find_candidates -> build_profiles -> lookup_evidence -> write_report -> check_citations.
retrieve.py (vector search, phase 1) is kept but not used by the pipeline."""
