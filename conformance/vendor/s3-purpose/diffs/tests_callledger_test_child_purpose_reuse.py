--- conformance/vendor/s3-purpose/upstream/tests/callledger/test_child_purpose_reuse.py
+++ conformance/vendor/s3-purpose/adapted/tests/callledger/test_child_purpose_reuse.py
@@ -2,8 +2,8 @@
 
 import pytest
 
-from llm_router_eval.shared.callledger.ledger import LedgerError, ReuseAccounting
-from llm_router_eval.shared.callledger.models import canonical_digest as h
+from content_strategy.shared.callledger.ledger import LedgerError, ReuseAccounting
+from content_strategy.shared.callledger.models import canonical_digest as h
 
 
 @pytest.fixture(autouse=True)
