"""Run history database (SQLite locally, PostgreSQL in deployment). See ADR 0005.

Files stay the source of truth for CI (ADR 0002); the database stores the history of
results for trends, drift and, later, the API and dashboard.
"""
