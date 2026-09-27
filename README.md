# obscura CentOS 7 兼容补丁

让 obscura v0.2.3(`obscura-x86_64-linux-no-render-stealth.tar.gz`,要求 glibc ≥ 2.34)
运行在 CentOS 7(glibc 2.17,kernel 3.10)上。已在 centos:7 用户态实测
`--version` / `fetch` / `scrape`(V8 JS 求值)通过。

## 使用

```bash
LD_PRELOAD=$PWD/shim.so LD_LIBRARY_PATH=$PWD ./patched/obscura --help
```

`LD_LIBRARY_PATH` 用于加载捆绑的 `libstdc++.so.6.0.28`
(二进制需要 `GLIBCXX_3.4.20`,C7 自带的 4.8.5 最高只有 `GLIBCXX_3.4.19`)。

## 组成

| 文件 | 作用 |
|---|---|
| `strip_versions.py` | 把 `.gnu.version` 中要求 GLIBC > 2.17 的符号索引清零为无版本绑定 |
| `rewrite_verneed.py` | 把 verneed 中 >2.17 的版本名改写为同长的 `GLIBC_2.15`,并重算 `vna_hash` |
| `obscura_c7_shim.c` / `shim.so` | 补齐 glibc 2.17 真缺的 12 个符号(见下) |
| `libstdc++.so.6.0.28` | gcc9 运行时,提供 GLIBCXX_3.4.20 |
| `patched/` | 打补丁后的 obscura / obscura-worker |

## 符号分析结论

315 个未定义版本化符号中,>2.17 的 53 处引用分两类:

- **29 个假缺失**:仅是 glibc 2.27~2.34 的版本重打标(2.34 合并 libpthread、
  2.33 实化 stat 族、2.27/2.29 数学函数新实现),2.17 内有语义相同的旧版本,
  剥离版本要求后直接绑定。
- **12 个真缺失**,由 shim.so 补齐:

| 符号 | 内核要求 | 3.10 回退策略 |
|---|---|---|
| `getrandom` | 3.17 | ENOSYS → `/dev/urandom` |
| `memfd_create` | 3.17 | ENOSYS → `shm_open` + unlink |
| `statx` | 4.11 | ENOSYS → `fstatat64` 字段映射 |
| `pkey_*` ×5 | 4.9 | 恒返 ENOSYS |
| `stat64`/`fstat64` | — | 转发 `__xstat64`/`__fxstat64` |
| `gettid` | 2.4 起 | 直接 syscall |
| `__cxa_thread_atexit_impl` | — | 降级为 `__cxa_atexit` |
| `posix_spawn_file_actions_addchdir_np` | — | 返 ENOSYS,Rust std 回退 fork+exec |

## 复现补丁流程

```bash
# 从原始 release 解出 obscura / obscura-worker 后:
python3 strip_versions.py obscura obscura-worker
python3 rewrite_verneed.py obscura obscura-worker
gcc -shared -fPIC -O2 -o shim.so obscura_c7_shim.c \
    -Wl,--no-as-needed -lpthread -ldl -lrt -Wl,--as-needed
```

`--no-as-needed` 是必须的:glibc 2.34 把 libpthread/libdl/librt 并入了 libc,
二进制不再 NEED 它们,但 C7 上 `dlsym`/`pthread_*` 仍住在独立的 .so 里,
靠 shim 的 DT_NEEDED 把它们拉进全局符号域。

## 已知保留项

- shim 的 ENOSYS 回退分支(`/dev/urandom`、`shm_open`、`fstatat64`)在开发机上
  未经真 3.10 内核触发验证(容器共享宿主内核)。
- `__cxa_thread_atexit_impl` 语义降级:TLS 析构推迟到进程退出。
- 更干净的替代方案:在 CentOS 7 容器或 musl target 下从源码重编译。
