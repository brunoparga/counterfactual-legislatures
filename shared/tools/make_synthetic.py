#!/usr/bin/env python3
"""Generate a synthetic state for smoke-testing the splitline engine.

A square of land with a controllable population field. With a uniform field
and N seats the answer is known by inspection: N equal-population blocks with
short, straight cuts. Handy for checking a port without waiting on real data.
"""
import argparse
import math


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="synth", help="output prefix")
    ap.add_argument("--lon0", type=float, default=-100.0)
    ap.add_argument("--lon1", type=float, default=-98.0)
    ap.add_argument("--lat0", type=float, default=40.0)
    ap.add_argument("--lat1", type=float, default=42.0)
    ap.add_argument("--step", type=float, default=0.01, help="degrees between points")
    ap.add_argument(
        "--field",
        choices=["uniform", "city"],
        default="uniform",
        help="uniform, or a dense blob in one corner",
    )
    args = ap.parse_args()

    with open(args.out + ".dat", "w") as f:
        cx = (args.lon0 + args.lon1) / 2
        cy = (args.lat0 + args.lat1) / 2
        f.write(f"{1:10d}{cx:15.6f}{cy:15.6f}\n")
        ring = [
            (args.lon0, args.lat0),
            (args.lon1, args.lat0),
            (args.lon1, args.lat1),
            (args.lon0, args.lat1),
            (args.lon0, args.lat0),
        ]
        for x, y in ring:
            f.write(f"{x:15.6f}{y:15.6f}\n")
        f.write("END\n")
        f.write("END\n")

    n = 0
    total = 0
    with open(args.out + ".pop", "w") as f:
        y = args.lat0
        while y <= args.lat1:
            x = args.lon0
            while x <= args.lon1:
                if args.field == "uniform":
                    p = 100
                else:
                    d = math.hypot(x - args.lon0, y - args.lat0)
                    p = int(100 + 5000 * math.exp(-((d / 0.25) ** 2)))
                f.write(f"{n % 999999:06d},1,{p},1,{x:.10f},{y:.10f}\n")
                total += p
                n += 1
                x += args.step
            y += args.step

    print(f"{args.out}.dat  {args.out}.pop  ({n} points, {total} people)")


if __name__ == "__main__":
    main()
