/* obscura CentOS 7 (glibc 2.17) 兼容 shim
 * 提供 glibc 2.18~2.34 新增、且 2.17 完全缺失的 12 个符号。
 * 编译: gcc -shared -fPIC -O2 -o shim.so obscura_c7_shim.c -ldl
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

/* ---- gettid (glibc 2.30) — syscall 186,kernel 2.4 起就有 ---- */
pid_t gettid(void) { return (pid_t)syscall(SYS_gettid); }

/* ---- getrandom (glibc 2.25, syscall 318, kernel 3.17+)
 *      3.10 无此 syscall → 回退 /dev/urandom ---- */
ssize_t getrandom(void *buf, size_t buflen, unsigned int flags) {
    long r = syscall(SYS_getrandom, buf, buflen, flags);
    if (r >= 0 || errno != ENOSYS) return r;
    if (flags != 0) { errno = EINVAL; return -1; }
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    size_t off = 0;
    while (off < buflen) {
        ssize_t n = read(fd, (char *)buf + off, buflen - off);
        if (n <= 0) { int e = errno; close(fd); errno = e; return -1; }
        off += (size_t)n;
    }
    close(fd);
    return (ssize_t)buflen;
}

/* ---- memfd_create (glibc 2.27, syscall 319, kernel 3.17+)
 *      回退: shm_open 随机名 + 立即 unlink ---- */
int memfd_create(const char *name, unsigned int flags) {
    long r = syscall(SYS_memfd_create, name, flags);
    if (r >= 0 || errno != ENOSYS) return (int)r;
    char tmpl[128];
    snprintf(tmpl, sizeof tmpl, "/obscura-mfd-%s-%d", name ? name : "x", getpid());
    int fd = shm_open(tmpl, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd >= 0) shm_unlink(tmpl);
    return fd;
}

/* ---- stat64/fstat64 (glibc 2.33 起成为真实导出符号;
 *      2.17 只在 libc_nonshared.a 里,运行时是 __xstat64/__fxstat64) ---- */
extern int __xstat64(int ver, const char *path, struct stat64 *buf);
extern int __fxstat64(int ver, int fd, struct stat64 *buf);
int stat64(const char *path, struct stat64 *buf) { return __xstat64(1, path, buf); }
int fstat64(int fd, struct stat64 *buf) { return __fxstat64(1, fd, buf); }

/* ---- statx (glibc 2.28, syscall 332, kernel 4.11+)
 *      回退: fstatat64 + 字段映射 ---- */
struct statx; /* 用宿主头文件里的完整定义 */
#include <sys/stat.h> /* 确保 struct statx 可见 */
#ifndef STATX_BASIC_STATS
#define STATX_BASIC_STATS 0x7ffu
#define STATX_ALL 0xfffu
#endif
int statx(int dirfd, const char *pathname, int flags, unsigned int mask,
          struct statx *statxbuf) {
    long r = syscall(SYS_statx, dirfd, pathname, flags, mask, statxbuf);
    if (r >= 0 || errno != ENOSYS) return (int)r;
    struct stat64 st;
    if (fstatat64(dirfd, pathname, &st, flags & AT_SYMLINK_NOFOLLOW) < 0)
        return -1;
    memset(statxbuf, 0, sizeof *statxbuf);
    statxbuf->stx_mask = STATX_BASIC_STATS;
    statxbuf->stx_blksize = (unsigned)st.st_blksize;
    statxbuf->stx_nlink = st.st_nlink;
    statxbuf->stx_uid = st.st_uid;
    statxbuf->stx_gid = st.st_gid;
    statxbuf->stx_mode = st.st_mode;
    statxbuf->stx_ino = st.st_ino;
    statxbuf->stx_size = st.st_size;
    statxbuf->stx_blocks = st.st_blocks;
    statxbuf->stx_atime.tv_sec = st.st_atime;
    statxbuf->stx_mtime.tv_sec = st.st_mtime;
    statxbuf->stx_ctime.tv_sec = st.st_ctime;
    return 0;
}

/* ---- pkey_* (glibc 2.27, syscall 330~334, kernel 4.9+ 且需 CPU PKU)
 *      3.10 无条件不支持 → 统一 ENOSYS,调用方会当作"无此能力" ---- */
int pkey_alloc(unsigned int flags, unsigned int rights) {
    (void)flags; (void)rights; errno = ENOSYS; return -1;
}
int pkey_free(int pkey) { (void)pkey; errno = ENOSYS; return -1; }
int pkey_mprotect(void *addr, size_t len, int prot, int pkey) {
    (void)addr; (void)len; (void)prot; (void)pkey; errno = ENOSYS; return -1;
}
int pkey_get(int pkey) { (void)pkey; errno = ENOSYS; return -1; }
int pkey_set(int pkey, unsigned int rights) {
    (void)pkey; (void)rights; errno = ENOSYS; return -1;
}

/* ---- posix_spawn_file_actions_addchdir_np (glibc 2.29)
 *      无法在不复制 glibc 内部结构的情况下实现;返回 ENOSYS。
 *      Rust std 仅在 Command 设置 current_dir 时走此路径,
 *      失败后 std 会回退 fork+exec 路径。 ---- */
int posix_spawn_file_actions_addchdir_np(posix_spawn_file_actions_t *fa,
                                         const char *path) {
    (void)fa; (void)path; return ENOSYS;
}

/* ---- __cxa_thread_atexit_impl (glibc 2.18)
 *      语义降级: TLS 析构改为进程退出时执行,而非线程退出时。
 *      对长驻进程影响小;线程频繁创建销毁时会延迟释放 TLS 资源。 ---- */
extern int __cxa_atexit(void (*func)(void *), void *arg, void *dso_handle);
int __cxa_thread_atexit_impl(void (*func)(void *), void *arg, void *dso_handle) {
    return __cxa_atexit(func, arg, dso_handle);
}
