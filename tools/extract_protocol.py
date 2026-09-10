#!/usr/bin/env python3
"""Recover the protobuf schema from an official Insta360 GO app.

This repository ships no Insta360 binaries. Supply your own copy of the app:

    python tools/extract_protocol.py Insta360Go_v1.3.4.apk -o extracted/

Verify what you downloaded before trusting it. The official build is signed
`CN=Insta360`:

    unzip -p app.apk 'META-INF/*.RSA' | openssl pkcs7 -inform DER \
        -print_certs -text -noout | grep -m1 Subject:

Requires `protobuf` (pip install "insta360-go-toolkit[protocol]").
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

NAME_RE = re.compile(rb"[a-z0-9_]+\.proto")
LIB = "lib/arm64-v8a/libOne.so"


def load_library(path: Path) -> bytes:
    """Return libOne.so, from an .apk or as a bare .so."""
    if path.suffix == ".so":
        return path.read_bytes()
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith("libOne.so")]
        if not names:
            raise SystemExit(f"{path}: no libOne.so inside. Is this the GO app?")
        preferred = LIB if LIB in names else names[0]
        return z.read(preferred)


def recover(blob: bytes, filename: str):
    """Find the longest valid FileDescriptorProto for `filename`.

    A truncated descriptor usually still parses cleanly, so stopping at the
    first success silently drops fields -- `OptionType` lives past that point
    in options.proto and disappears entirely if you take the first parse.
    """
    from google.protobuf import descriptor_pb2

    target = filename.encode()
    best = None
    for match in re.finditer(re.escape(target), blob):
        for back in (2, 3):                       # length varint is 1 or 2 bytes
            start = match.start() - back
            if start < 0 or blob[start] != 0x0A:  # field 1 (name), wire type 2
                continue
            found = None
            limit = min(len(blob) - start, 80_000)
            for size in range(len(target) + back, limit):
                fd = descriptor_pb2.FileDescriptorProto()
                try:
                    fd.ParseFromString(blob[start:start + size])
                except Exception:
                    continue
                if fd.name == filename:
                    found = (size, fd)            # keep going: want the longest
            if found and (best is None or found[0] > best[0]):
                best = found
    return best[1] if best else None


def render(fd) -> str:
    from google.protobuf import descriptor_pb2

    out = ['// recovered from libOne.so\nsyntax = "proto2";\n']
    if fd.package:
        out.append(f"package {fd.package};\n")

    def type_name(f):
        return (f.type_name.lstrip(".").split(".")[-1]
                or descriptor_pb2.FieldDescriptorProto.Type.Name(f.type)
                .replace("TYPE_", "").lower())

    def msg(m, indent=""):
        out.append(f"{indent}message {m.name} {{")
        for f in m.field:
            label = {1: "optional", 2: "required", 3: "repeated"}.get(f.label, "")
            out.append(f"{indent}  {label} {type_name(f)} {f.name} = {f.number};")
        for e in m.enum_type:
            enum(e, indent + "  ")
        for n in m.nested_type:
            msg(n, indent + "  ")
        out.append(f"{indent}}}")

    def enum(e, indent=""):
        out.append(f"{indent}enum {e.name} {{")
        for v in e.value:
            out.append(f"{indent}  {v.name} = {v.number};")
        out.append(f"{indent}}}")

    for m in fd.message_type:
        msg(m)
    for e in fd.enum_type:
        enum(e)
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("apk", type=Path, help="official Insta360 GO .apk (or libOne.so)")
    ap.add_argument("-o", "--out", type=Path, default=Path("extracted"))
    ap.add_argument("--only", nargs="*", help="specific .proto names")
    args = ap.parse_args()

    try:
        blob = load_library(args.apk)
    except FileNotFoundError as exc:
        raise SystemExit(f"{args.apk}: not found") from exc
    print(f"scanning {len(blob):,} bytes")

    names = args.only or sorted({n.decode() for n in NAME_RE.findall(blob)})
    args.out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for name in names:
        fd = recover(blob, name)
        if fd is None:
            print(f"  {name}: could not recover")
            continue
        (args.out / name).write_text(render(fd))
        counts = f"{len(fd.message_type)} messages, {len(fd.enum_type)} enums"
        print(f"  {name}: {counts}")
        ok += 1
    print(f"\nrecovered {ok}/{len(names)} into {args.out}/")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
