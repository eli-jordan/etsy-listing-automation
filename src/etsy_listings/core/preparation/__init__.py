"""Explicit authoring preparation, separate from CPU rendering (ADR-0053).

Import modules directly. Runtime owns global installation; worker_client owns
subprocess communication, including idle restart. Predictions validates numeric
evidence without loading model packages. Installation and the embedded worker
distribution are implementation details reached through Runtime.
Importing this package never starts workers or loads torch.
"""
