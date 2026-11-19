# Separate finish, abort and pause for operator control

Status: accepted

A single "stop" cannot satisfy "settle and keep the current run", "stop immediately without optional keep" and "let the current run finish but do not start the next". The farmer therefore exposes `finish`, `abort`, `pause` and `resume` through a command file; the existing stop file remains a `finish` alias. Commands are consumed at phase boundaries.

## Consequences

- Emergency stops do not silently change settlement semantics.
- `pause` never interrupts a run; it only prevents the next start.
- The supervisor and GUI can use the same command interface.
