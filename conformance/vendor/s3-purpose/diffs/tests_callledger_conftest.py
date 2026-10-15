--- conformance/vendor/s3-purpose/upstream/tests/callledger/conftest.py
+++ conformance/vendor/s3-purpose/adapted/tests/callledger/conftest.py
@@ -4,8 +4,8 @@
 
 import pytest
 
-from llm_router_eval.shared.callledger.ledger import Ledger
-from llm_router_eval.shared.callledger.models import (
+from content_strategy.shared.callledger.ledger import Ledger
+from content_strategy.shared.callledger.models import (
     BudgetAuthority,
     CallContext,
     ChildBound,
@@ -15,10 +15,10 @@
     NormalizedUsage,
     OperationPlan,
 )
-from llm_router_eval.shared.callledger.models import (
+from content_strategy.shared.callledger.models import (
     canonical_digest as digest,
 )
-from llm_router_eval.shared.callledger.pricing import (
+from content_strategy.shared.callledger.pricing import (
     FundingEvidence,
     PricePolicy,
     PriceProvenance,
