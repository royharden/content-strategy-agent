--- conformance/vendor/s3-purpose/upstream/tests/providers/conftest.py
+++ conformance/vendor/s3-purpose/adapted/tests/providers/conftest.py
@@ -5,33 +5,33 @@
 
 import pytest
 
-from llm_router_eval.shared.callledger import Ledger
-from llm_router_eval.shared.callledger.models import (
+from content_strategy.shared.callledger import Ledger
+from content_strategy.shared.callledger.models import (
     BudgetAuthority,
     CallContext,
     ChildBound,
     Limits,
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
     PriceSnapshot,
     RequestEvidence,
 )
-from llm_router_eval.shared.providers.adapters import (
+from content_strategy.shared.providers.adapters import (
     ModelSupport,
     ProviderConfig,
     decode_outcome,
     prepare_request,
 )
-from llm_router_eval.shared.providers.captures import synthetic_capture
-from llm_router_eval.shared.providers.controller import Provider, TransportReply
-from llm_router_eval.shared.providers.models import GenerateRequest, TypedJudgmentRequest
+from content_strategy.shared.providers.captures import synthetic_capture
+from content_strategy.shared.providers.controller import Provider, TransportReply
+from content_strategy.shared.providers.models import GenerateRequest, TypedJudgmentRequest
 
 
 class Rig:
