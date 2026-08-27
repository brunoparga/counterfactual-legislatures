CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra -Wno-unused-parameter -std=gnu11
LDLIBS  := -lm -lz

all: bin/splitline bin/splitline_raster

bin/splitline: src/splitline.c | bin
	$(CC) $(CFLAGS) $< -o $@ $(LDLIBS)

# The 2007-style raster engine, kept for cross-checking the point-based one.
bin/splitline_raster: src/splitline_raster.c | bin
	$(CC) $(CFLAGS) $< -o $@ -lm

bin:
	mkdir -p bin

clean:
	rm -rf bin

.PHONY: all clean
