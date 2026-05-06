"""
Maker-order planning layer (Kalshi, paper-only, disabled by default).

Commit 1 surface: policy + math + types only.  No I/O, no order placement,
no integration into the scan/snapshot pipeline.  Live trading is never
performed in v1.

Public entry point: ``plan_maker_proposal`` in ``services.maker.planner``.
"""
