--- conformance/vendor/s3-purpose/upstream/tests/providers/test_child_purpose_controller.py
+++ conformance/vendor/s3-purpose/adapted/tests/providers/test_child_purpose_controller.py
@@ -4,10 +4,10 @@
 
 import pytest
 
-from llm_router_eval.shared.callledger.ledger import LedgerError
-from llm_router_eval.shared.callledger.models import canonical_digest as h
-from llm_router_eval.shared.providers.adapters import decode_outcome, prepare_request
-from llm_router_eval.shared.providers.captures import FixtureIndex, synthetic_capture
+from content_strategy.shared.callledger.ledger import LedgerError
+from content_strategy.shared.callledger.models import canonical_digest as h
+from content_strategy.shared.providers.adapters import decode_outcome, prepare_request
+from content_strategy.shared.providers.captures import FixtureIndex, synthetic_capture
 
 
 @pytest.fixture(autouse=True)
