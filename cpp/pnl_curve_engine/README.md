# C++ PnL Curve Engine

This module only calculates bucket-level PnL curves. It does not submit orders
and must not bypass Python `risk_manager`.

Input is CSV:

```text
bucket,price,shares,model_probability
86F_or_below,0.05,1,0.09
87F,0.24,2,0.30
```

Output is CSV:

```text
bucket,price,shares,cost,model_probability,edge,pnl_if_wins
```

Build:

```bash
cmake -S cpp/pnl_curve_engine -B build/pnl_curve_engine
cmake --build build/pnl_curve_engine
```

Run:

```bash
./build/pnl_curve_engine/pnl_curve_engine data/sample_buckets.csv
```
