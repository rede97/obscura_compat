#!/usr/bin/env python3
"""Strip symbol-version requirements above glibc 2.17 from an ELF64 binary.
Sets .gnu.version index to 1 (VER_NDX_GLOBAL = unversioned) for any
undefined dynsym whose required GLIBC_ version is > 2.17, so ld.so binds
it to whatever version (or LD_PRELOAD shim) is present at runtime.
"""
import struct, sys

def parse_version(name):
    # "GLIBC_2.27" -> (2,27); "GLIBC_2.2.5" -> (2,2,5)
    if not name.startswith("GLIBC_"):
        return None
    return tuple(int(x) for x in name[6:].split("."))

def main(path):
    data = bytearray(open(path, "rb").read())
    assert data[:4] == b"\x7fELF" and data[4] == 2, "need ELF64"
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, = struct.unpack_from("<H", data, 0x3A)
    e_shnum, = struct.unpack_from("<H", data, 0x3C)
    e_shstrndx, = struct.unpack_from("<H", data, 0x3E)

    secs = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        secs.append(struct.unpack_from("<IIQQQQIIQQ", data, off))
    shstr = secs[e_shstrndx]
    def secname(s):
        o = shstr[4] + s[0]
        return data[o:data.index(b"\0", o)].decode()

    versym = verneed = dynstr = dynsym = None
    for s in secs:
        n = secname(s)
        if n == ".gnu.version": versym = s
        elif n == ".gnu.version_r": verneed = s
        elif n == ".dynstr": dynstr = s
        elif n == ".dynsym": dynsym = s
    assert versym and verneed and dynstr and dynsym

    def dstr(o):
        p = dynstr[4] + o
        return data[p:data.index(b"\0", p)].decode()

    # verneed walk: idx -> version name
    idx2name = {}
    base = verneed[4]
    vn_off = 0
    while True:
        vn_version, vn_cnt, vn_file, vn_aux, vn_next = struct.unpack_from("<HHIII", data, base + vn_off)
        lib = dstr(vn_file)
        a_off = vn_off + vn_aux
        for _ in range(vn_cnt):
            vna_hash, vna_flags, vna_other, vna_name, vna_next = struct.unpack_from("<IHHII", data, base + a_off)
            idx2name[vna_other] = (lib, dstr(vna_name))
            if vna_next == 0: break
            a_off += vna_next
        if vn_next == 0: break
        vn_off += vn_next

    nsyms = dynsym[5] // dynsym[9]  # sh_size / sh_entsize
    patched = {}
    for i in range(nsyms):
        voff = versym[4] + i * 2
        raw, = struct.unpack_from("<H", data, voff)
        idx = raw & 0x7FFF
        if idx < 2 or idx not in idx2name:
            continue
        lib, vname = idx2name[idx]
        pv = parse_version(vname)
        if pv and pv > (2, 17):
            # symbol name for reporting
            soff = dynsym[4] + i * dynsym[9]
            st_name, = struct.unpack_from("<I", data, soff)
            struct.pack_into("<H", data, voff, 1)
            patched.setdefault(f"{vname} ({lib})", []).append(dstr(st_name))

    open(path, "wb").write(data)
    for k in sorted(patched):
        syms = sorted(set(patched[k]))
        print(f"  stripped {k}: {len(syms)} syms -> {', '.join(syms[:6])}{' ...' if len(syms) > 6 else ''}")
    print(f"{path}: {sum(len(v) for v in patched.values())} refs stripped")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
