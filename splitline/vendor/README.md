# Vendored upstream

`autodistrict-2007/` is the tip of the `bmp_version` module of the autodistrict
CVS repository (Ivan Ryan, 2007, Apache-2.0), which lives in `autodistrict/` at
the repo root and is not tracked by git.

To re-check it out:

    cvs -d "$PWD/autodistrict" checkout bmp_version

## What is in the history

Nothing that affects the port. The full log is nine commits on 2007-08-09/10:

| file              | revs | what changed                                        |
|-------------------|------|-----------------------------------------------------|
| `block_display.c` | 1.2  | Apache licence header only; no code change          |
| `geoproc.c`       | 1.2  | Apache licence header only; no code change          |
| `compile`         | 1.3  | added `-Wl,--stack,300388608 -mno-cygwin` to geoproc |
| `gen_block_scr`   | 1.3  | corrected the path to the `geoproc` binary          |

The `compile` change is the one useful signal: `geoproc.c` declares ~160 MB of
arrays as function locals, so upstream had to ask the linker for a 300 MB
stack. Any port has to move those to the heap or hit the same wall.

## svg_version

The repository also contains an `svg_version` module. It is a verbatim copy of
`bmp_version` taken on 2007-09-04, with every file still at revision 1.1 and a
single blank line added to `geoproc.c`. There is no SVG implementation; the
module was created and never worked on. Ignore it.
