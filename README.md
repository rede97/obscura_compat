# obscura CentOS 7 兼容补丁

让 obscura v0.2.3(`obscura-x86_64-linux-no-render-stealth.tar.gz`,要求 glibc ≥ 2.34)
运行在 CentOS 7(glibc 2.17,kernel 3.10)上。已在 centos:7 用户态实测
`--version` / `fetch` / `scrape`(V8 JS 求值)通过。

## 安装

从 [Releases](../../releases) 下载对应变体(变体差异:`no-render` 去掉截图/PDF 渲染,
`stealth` 增加 TLS 指纹伪装 + tracker 拦截;日常抓取推荐 `no-render-stealth`):

```bash
# 1. 下载并解压到固定位置
mkdir -p ~/.local/share
curl -LO https://github.com/rede97/obscura_compat/releases/latest/download/obscura-c7-x86_64-linux-no-render-stealth.tar.gz
tar xzf obscura-c7-*.tar.gz -C ~/.local/share
mv ~/.local/share/obscura-c7-* ~/.local/share/obscura-c7

# 2. 入口脚本链接进 PATH(脚本会 readlink -f 解析符号链接,无需改任何配置)
mkdir -p ~/.local/bin
ln -sf ~/.local/share/obscura-c7/obscura_c7 ~/.local/bin/obscura_c7

# 3. 验证
obscura_c7 --version
obscura_c7 fetch https://example.com
```

包结构与自定义:

```
~/.local/share/obscura-c7/
├── obscura_c7              # 入口脚本;顶部 OBSCURA_C7_HOME 变量可写死安装路径
├── bin/
│   ├── obscura_c7          # 打补丁的主二进制
│   └── obscura-worker      # 打补丁的 worker(必须保留原名:scrape 硬编码按名查找)
└── lib/
    ├── shim.so             # glibc 2.17 缺失符号补齐
    ├── libstdc++.so.6.0.28 # gcc9 运行时,提供 GLIBCXX_3.4.20
    └── libstdc++.so.6 -> libstdc++.so.6.0.28
```

> 若把入口脚本单独拷贝到别处(脱离包目录),需把脚本顶部
> `OBSCURA_C7_HOME` 改为安装目录的绝对路径,例如 `OBSCURA_C7_HOME=/opt/obscura-c7`。

## 实践示例

```bash
# 单页抓取,输出纯文本 / markdown / 链接清单
obscura_c7 fetch https://example.com --dump text
obscura_c7 fetch https://example.com --dump markdown

# 执行 JS 表达式
obscura_c7 fetch https://example.com --eval "document.title"

# 批量并行抓取(依赖 bin/obscura-worker)
obscura_c7 scrape https://example.com https://www.iana.org/domains/example \
  --concurrency 10 --eval "document.title" --format json

# 反检测模式(stealth 构建:伪装浏览器指纹 + TLS 指纹 + 拦截 tracker)
obscura_c7 --stealth fetch https://example.com

# 启动 CDP 服务,供 Puppeteer / Playwright 连接(ws://127.0.0.1:9222)
obscura_c7 serve --port 9222

# 启动 MCP 服务,供 Claude Desktop / Cursor 等 AI 客户端调用
obscura_c7 mcp
```

Puppeteer 连接示例:

```javascript
import puppeteer from 'puppeteer-core';
const browser = await puppeteer.connect({
  browserWSEndpoint: 'ws://127.0.0.1:9222/devtools/browser',
});
const page = await browser.newPage();
await page.goto('https://example.com');
console.log(await page.title());
await browser.disconnect();
```

> 注意:obscura 默认拦截指向私有地址(SSRF 防护,#4)。抓取
> `localhost` / 内网地址时需显式加 `--allow-private-network`。

## CI 自动跟踪上游

`.github/workflows/centos7-patch.yml` 每周一轮询上游
[h4ckf0r0day/obscura](https://github.com/h4ckf0r0day/obscura) 的最新 release:
发现新版本即下载全部 4 个 x86_64-linux 变体 → 打补丁 → 在 centos:7 容器中
冒烟测试(`--version` / `fetch` / `scrape`)→ 发布 `c7-<tag>` release,
并把版本号记入 `upstream-version`。修改 patcher/shim 的 push 会立即重建当前版本。

## 组成

| 文件 | 作用 |
|---|---|
| `strip_versions.py` | 把 `.gnu.version` 中要求 GLIBC > 2.17 的符号索引清零为无版本绑定 |
| `rewrite_verneed.py` | 把 verneed 中 >2.17 的版本名改写为同长的 `GLIBC_2.15`,并重算 `vna_hash` |
| `obscura_c7_shim.c` / `shim.so` | 补齐 glibc 2.17 真缺的 12 个符号(见下) |
| `libstdc++.so.6.0.28` | gcc9 运行时,提供 GLIBCXX_3.4.20 |
| `bin/` | 打补丁后的 obscura_c7 / obscura-worker(CI 产物,见 Releases) |

> 注:`patched/`、`shim.so`、`libstdc++.so.6*` 为生成物,未纳入 git(见 `.gitignore`),
> 按下文「复现补丁流程」可在数分钟内重建。

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
    -Wl,--no-as-needed \
    /lib/x86_64-linux-gnu/libpthread.so.0 \
    /lib/x86_64-linux-gnu/libdl.so.2 \
    /lib/x86_64-linux-gnu/librt.so.1 \
    -Wl,--as-needed
```

注意:现代 glibc (>=2.34) 的 `-lpthread/-ldl/-lrt` 链接脚本不再引用兼容
`.so.0`,即使 `--no-as-needed` 也不会产生 `DT_NEEDED`,必须直接链接库文件。
glibc 2.34 把 libpthread/libdl/librt 并入了 libc,
二进制不再 NEED 它们,但 C7 上 `dlsym`/`pthread_*` 仍住在独立的 .so 里,
靠 shim 的 DT_NEEDED 把它们拉进全局符号域。

## 已知保留项

- shim 的 ENOSYS 回退分支(`/dev/urandom`、`shm_open`、`fstatat64`)在开发机上
  未经真 3.10 内核触发验证(容器共享宿主内核)。
- `__cxa_thread_atexit_impl` 语义降级:TLS 析构推迟到进程退出。
- 更干净的替代方案:在 CentOS 7 容器或 musl target 下从源码重编译。
