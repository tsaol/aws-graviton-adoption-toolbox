# harness

Repro harness (planned for v0.2). It starts one x86 and one Graviton Spot instance, builds the same commit with several compilers, optimization levels and sanitizers (ASan, TSan, UBSan), runs the tests, compares the results and then shuts the instances down.
