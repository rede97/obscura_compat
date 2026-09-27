#!/usr/bin/env python3
"""Neutralize verneed aux entries requiring GLIBC_ > 2.17 by rewriting the
version NAME STRING in .dynstr in place to a same-length version that the
target library (CentOS 7 glibc 2.17) actually defines. Versym indices for
these symbols were already set to unversioned by strip_versions.py, so the
rewritten name is only there to satisfy ld.so's load-time verneed check.
"""
import struct, sys

# 统一替换为 GLIBC_2.15:C7 的 libc 和 libm 的 verdef 都定义它,长度 10 与全部目标一致。
# dynstr 字符串被多个 aux 共享,故先改字符串,再按偏移给所有引用者统一刷 hash。
REPL = "GLIBC_2.15"

def parse_version(name):
    if not name.startswith("GLIBC_"):
        return None
    return tuple(int(x) for x in name[6:].split("."))
def elf_hash(name):
    h = 0
    for c in name.encode():
        h = ((h << 4) + c) & 0xFFFFFFFF
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g
    return h

def main(path):
    data = bytearray(open(path, "rb").read())
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, = struct.unpack_from("<H", data, 0x3A)
    e_shnum, = struct.unpack_from("<H", data, 0x3C)
    e_shstrndx, = struct.unpack_from("<H", data, 0x3E)
    secs = [struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    shstr = secs[e_shstrndx]
    def secname(s):
        o = shstr[4] + s[0]
        return bytes(data[o:data.index(b"\0", o)]).decode()
    verneed = dynstr = None
    for s in secs:
        n = secname(s)
        if n == ".gnu.version_r": verneed = s
        elif n == ".dynstr": dynstr = s
    if not verneed:
        print(f"{path}: no verneed"); return
    def dstr(o):
        p = dynstr[4] + o
        return bytes(data[p:data.index(b"\0", p)]).decode()

    # pass 0: 收集所有 aux 条目 (绝对偏移, name 字符串偏移)
    auxes = []
    base = verneed[4]
    vn_off = 0
    while True:
        vn_version, vn_cnt, vn_file, vn_aux, vn_next = struct.unpack_from("<HHIII", data, base + vn_off)
        a_off = vn_off + vn_aux
        for _ in range(vn_cnt):
            vna_hash, vna_flags, vna_other, vna_name, vna_next = struct.unpack_from("<IHHII", data, base + a_off)
            auxes.append((base + a_off, vna_name))
            if vna_next == 0: break
            a_off += vna_next
        if vn_next == 0: break
        vn_off += vn_next
    # pass 1: 改写 >2.17 的版本名字符串,记录被改的 dynstr 偏移
    rewritten = {}
    hit_offsets = set()
    for a_abs, name_off in auxes:
        name = dstr(name_off)
        pv = parse_version(name)
        if pv and pv > (2, 17):
            assert len(REPL) == len(name), f"length mismatch {name}"
            p = dynstr[4] + name_off
            data[p:p + len(REPL)] = REPL.encode()
            hit_offsets.add(name_off)
            rewritten[name] = REPL
    # pass 2: 所有引用被改字符串的 aux 统一刷 hash(覆盖共享字符串的条目)
    n_hash = 0
    for a_abs, name_off in auxes:
        if name_off in hit_offsets:
            struct.pack_into("<I", data, a_abs, elf_hash(REPL))
            n_hash += 1

    open(path, "wb").write(data)
    for k, v in sorted(rewritten.items()):
        print(f"  {k} -> {v}")
    print(f"{path}: {len(rewritten)} names rewritten, {n_hash} aux hashes refreshed")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
