# Changelog

## [0.1.0] - 2026-03-31

### Added
- Full Phase 1 implementation (Steps 00-11)
- Decision capsule compiler with audit gate
- File-touch invalidation + stale quarantine
- Resume handshake + SessionEnd snapshot
- Verify results recorder + attempt family clustering
- MCP inspect tools (6 read-only tools)
- Local read-only inspector (stdlib HTTP)
- Structured logging + metrics + recovery CLI
- Benchmark harness with Go/No-Go evaluation
- Plugin packaging (pip install + egtsr CLI)
- Claude Code plugin manifest (.claude-plugin/plugin.json)
- 4 user-invocable skills
- 164 tests passing

### Benchmarks
- Token savings: 63-82% vs raw transcript
- Hook latency: ~70ms avg
- Go/No-Go verdict: CONTINUE
