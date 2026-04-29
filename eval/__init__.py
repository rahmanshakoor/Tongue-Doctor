"""Eval harness — eval-driven development for the diagnostic loop.

Cases under ``eval/cases/<complaint>/<case_id>.yaml`` describe the contract: input →
expected behaviour. The runner discovers cases, runs them through the diagnostic loop,
applies scorers, writes a report under ``eval/reports/runs/``. See
``docs/EVAL_PROCESS.md`` for the case format and scoring weights.
"""
