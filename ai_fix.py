# AI-generated fix for #450
Remove unnecessary storage of on-chain service id in synchronized data
```diff
--- a/packages/valory/skills/trader_abci/handlers.py
+++ b/packages/valory/skills/trader_abci/handlers.py
@@ -180,7 +180,6 @@
     def setup(self) -> None:
         ...
         self.params = params
-        self.on_chain_service_id = params.on_chain_service_id
         ...

@@ -300,7 +299,6 @@
     def some_method(self) -> None:
         ...
-        on_chain_service_id = self.on_chain_service_id
+        on_chain_service_id = self.params.on_chain_service_id
         ...
```