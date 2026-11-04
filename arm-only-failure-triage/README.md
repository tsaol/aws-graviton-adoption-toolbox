# arm-only-failure-triage

Triage skill for failures that only happen on Arm (planned for v0.2). C/C++ first.

Thesis: the most common mistake on a first Arm-only crash is to call it "weak memory ordering" right away. Rule causes out one by one, reproduce on both architectures, and only then name the root cause.

| Candidate cause | How to check |
|---|---|
| Memory ordering (x86 TSO vs Arm weak ordering) | TSan; switch suspect atomics to seq_cst and see if the failure goes away |
| Compiler bug or optimization difference | Change GCC/Clang version and optimization level, bisect |
| Allocator version mix-up | Check jemalloc/tcmalloc versions and load order; look at which lock a core dump is stuck on |
| `char` signedness | Rebuild with `-fsigned-char` |
| Floating point | Compare with x86 results; FMA contraction, `-ffp-contract` |
| Wrong native libraries | Check `.so` / `.a` / JNI files against the target OS and architecture |
| Page size, THP, kernel settings | Compare MALLOC_CONF and THP settings |

Step one calls the Arm MCP Server scan. This skill covers the runtime part that the scan does not.
