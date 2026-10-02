# Source fidelity and unresolved definitions

`docs/BOOTSTRAP.pdf` is the supplied source, preserved unchanged. `BOOTSTRAP.md`
is the complete `pdftotext -layout` extraction with page-break characters removed;
PDF line wraps, typography, and clipped content remain. `AGENTS.md` is section 1
of that extraction verbatim, excluding the instruction heading. Documents for
sections 0–5 preserve the extracted source. The latest v2 source supersedes the
v1 bootstrap in the initial chat.

The PDF has visible clipping: architecture ends with `edge boa`, the setup
fallback command ends with `websoc`, and the FVG condition renders
`= 0.1 x ATR`. These are preserved rather than repaired by assumption.
Implementation must resolve whether FVG requires `>= 0.1 x ATR` before T11.

Section 4 supplies no defaults for the following configurable decisions:
OFI normalization window; iceberg window; absorption dominance fraction; Kyle
return convention; ATR smoothing; equal-swing tie treatment; profile side and
POC distance tie treatment; initial balance extension multiples; VIX regime
thresholds; morning/midday/afternoon boundaries; liquidity tier thresholds;
zone linkage, invalidation and touch policies; S5 direction confirmation;
risk per trade; and walk-forward fold/purge/embargo lengths. Their configuration
values are `null`. This explicitly records missing requirements and avoids
claiming an exact definition for an invented parameter.

Operational queue/batch/flush sizes, rescue/history schedule times, retry delay,
volume bar size, instrument/calendar paths and credentials paths are also unset.
Resolve them in their task; they are not Cloud secrets.

The source's parallel-group sentence puts T18 late, while its task row depends
only on T02/T03/T05. The user's explicit deployment priority and that dependency
row govern: T01 → T02/T03/T05 → T18 before research layers.
