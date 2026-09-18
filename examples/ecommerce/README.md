# Ecommerce migration example

This synthetic inventory demonstrates the three principal routing decisions:

- `customers` is a flat relational table and maps to Fabric Warehouse.
- `orders` contains repeated structured data and maps to Fabric Lakehouse.
- `clickstream` is an event workload and maps to Fabric Eventhouse.

Generate the review package with:

```powershell
bqtofabric generate examples/ecommerce/inventory.json --output artifacts/ecommerce
```
