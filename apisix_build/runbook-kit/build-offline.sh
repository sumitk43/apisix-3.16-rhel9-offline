#!/usr/bin/env bash
# Run one phase at a time: bash build-offline.sh PHASE BUILD_ROOT
set -euo pipefail
phase="${1:?Specify generate, extract, patches, openssl, openresty, luarocks, or apisix}"
root="$(cd "${2:?Specify build root}" && pwd)"
kit="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
mkdir -p logs work repo
export PATH="/usr/local/openresty/bin:/usr/local/openresty/luajit/bin:/usr/local/bin:$PATH"
export LD_LIBRARY_PATH="/usr/local/openresty/openssl/lib:/usr/local/openresty/wasmtime-c-api/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
prefix=/usr/local/openresty
modules="$root/work/sources"
source="$root/work/openresty-offline/openresty-1.31.1.1"
case "$phase" in
generate)
    python3 "$kit/generate-patches.py" "$root"
    ;;
extract)
    test ! -e "$modules" || { echo 'Sources already exist; use a clean workspace.'; exit 1; }
    mkdir -p "$modules" "$root/work/openresty-offline"
    for spec in apisix-nginx-module-1.19.10 mod_dubbo-1.0.2 ngx_multi_upstream_module-1.3.4 wasm-nginx-module-0.7.0 lua-var-nginx-module-v0.5.3 lua-resty-events-0.2.0 lua-resty-limit-traffic-1.2.0 ngx_http_ffi_client-v0.1.3; do
        mkdir -p "$modules/$spec"
        tar --no-same-owner -xzf "$root/downloads/$spec.tar.gz" --strip-components=1 -C "$modules/$spec"
    done
    tar --no-same-owner -xzf downloads/openresty-1.31.1.1.tar.gz -C work/openresty-offline
    tar --no-same-owner -xzf downloads/apisix-3.18.0.tar.gz -C work
    mkdir -p work/wasmtime-c-api
    tar --no-same-owner -xJf downloads/wasmtime-v0.38.1-x86_64-linux-c-api.tar.xz --strip-components=1 -C work/wasmtime-c-api
    test -f work/wasmtime-c-api/include/wasmtime.h
    test -f work/wasmtime-c-api/lib/libwasmtime.so
    ;;
patches)
    test ! -e repo/work-patches
    mkdir -p repo/work-patches
    tar --no-same-owner -xzf downloads/apisix318-openresty1311-generated-patches.tar.gz -C repo/work-patches
    (cd repo/work-patches && sha256sum -c SHA256SUMS)
    patches="$root/repo/work-patches/custom-patches"
    test "$(find "$patches/apisix-nginx-module-1.31.1-full" -maxdepth 1 -name '*.patch' | wc -l)" -eq 37
    apply() {
        patch --dry-run --forward --batch --fuzz=0 --no-backup-if-mismatch -p0 -d "$2" < "$1"
        patch --forward --batch --fuzz=0 --no-backup-if-mismatch -p0 -d "$2" < "$1"
    }
    apply "$patches/nginx-1.31.1.patch" "$source/bundle/nginx-1.31.1"
    export LC_ALL=C
    for group in nginx lua-resty-core ngx_lua ngx_stream_lua; do
        case "$group" in
            nginx) component=nginx-1.31.1;;
            lua-resty-core) component=lua-resty-core-0.1.34rc3;;
            ngx_lua) component=ngx_lua-0.10.31rc5;;
            ngx_stream_lua) component=ngx_stream_lua-0.0.19rc4;;
        esac
        for file in "$patches/apisix-nginx-module-1.31.1-full/$group"-*.patch; do
            apply "$file" "$source/bundle/$component"
        done
    done
    echo 'ALL 38 PATCHES APPLIED'
    ;;
openssl)
    test ! -e work/openssl-build
    mkdir -p work/openssl-build
    tar --no-same-owner -xzf downloads/openssl-3.4.1.tar.gz -C work/openssl-build
    cd work/openssl-build/openssl-3.4.1
    ./config --prefix="$prefix/openssl" --openssldir="$prefix/openssl/ssl" --libdir=lib shared
    make -j2
    make test
    make install_sw
    "$prefix/openssl/bin/openssl" version -a
    ;;
openresty)
    test -f "$source/bundle/ngx_lua-0.10.31rc5/src/api/ngx_http_lua_api.h"
    test -f "$prefix/openssl/lib/libssl.so.3"
    if [ ! -e "$modules/wasm-nginx-module-0.7.0/wasmtime-c-api" ]; then
        cp -a work/wasmtime-c-api "$modules/wasm-nginx-module-0.7.0/wasmtime-c-api"
    fi
    mkdir -p "$prefix/wasmtime-c-api"
    cp -a work/wasmtime-c-api/. "$prefix/wasmtime-c-api/"
    if [ ! -e "$modules/lua-nginx-module" ] && [ ! -L "$modules/lua-nginx-module" ]; then
        ln -s "$source/bundle/ngx_lua-0.10.31rc5" "$modules/lua-nginx-module"
    fi
    test -f "$modules/lua-nginx-module/src/api/ngx_http_lua_api.h"
    export NGX_HTTP_LUA_MODULE_DIR="$modules/lua-nginx-module"
    cd "$source"
    ./configure \
      --prefix="$prefix" \
      --with-cc-opt="-DAPISIX_RUNTIME_VER=1.3.16 -DNGX_LUA_ABORT_AT_PANIC -I$prefix/openssl/include" \
      --with-ld-opt="-L$prefix/openssl/lib -Wl,-rpath,$prefix/openssl/lib -Wl,-rpath,$prefix/wasmtime-c-api/lib" \
      --add-module="$modules/mod_dubbo-1.0.2" \
      --add-module="$modules/ngx_multi_upstream_module-1.3.4" \
      --add-module="$modules/apisix-nginx-module-1.19.10" \
      --add-module="$modules/apisix-nginx-module-1.19.10/src/stream" \
      --add-module="$modules/apisix-nginx-module-1.19.10/src/meta" \
      --add-module="$modules/wasm-nginx-module-0.7.0" \
      --add-module="$modules/lua-var-nginx-module-v0.5.3" \
      --add-module="$modules/lua-resty-events-0.2.0" \
      --add-module="$modules/ngx_http_ffi_client-v0.1.3" \
      --without-pcre2 --with-pcre-jit --with-poll_module \
      --with-stream --with-stream_ssl_module \
      --with-stream_ssl_preread_module --with-stream_realip_module \
      --with-http_ssl_module --with-http_v2_module --with-http_v3_module \
      --with-http_stub_status_module --with-http_realip_module \
      --with-http_addition_module --with-http_auth_request_module \
      --with-http_secure_link_module --with-http_random_index_module \
      --with-http_gzip_static_module --with-http_sub_module \
      --with-http_dav_module --with-http_flv_module --with-http_mp4_module \
      --with-http_gunzip_module --with-threads --with-compat \
      --with-luajit-xcflags="-DLUAJIT_NUMMODE=2 -DLUAJIT_ENABLE_LUA52COMPAT"
    make -j2
    make install
    mkdir -p "$prefix/site/lualib"
    cp -a "$modules/apisix-nginx-module-1.19.10/lib/." "$prefix/site/lualib/"
    cp -a "$modules/lua-resty-events-0.2.0/lualib/." "$prefix/site/lualib/"
    cp -a "$modules/lua-resty-limit-traffic-1.2.0/lib/." "$prefix/site/lualib/"
    "$prefix/nginx/sbin/nginx" -V
    ldd "$prefix/nginx/sbin/nginx"
    "$prefix/luajit/bin/luajit" -v
    ;;
luarocks)
    test ! -e work/luarocks-build
    mkdir -p work/luarocks-build
    tar --no-same-owner -xzf downloads/luarocks-3.11.1.tar.gz -C work/luarocks-build
    cd work/luarocks-build/luarocks-3.11.1
    ./configure --prefix=/usr/local --lua-version=5.1 \
      --with-lua="$prefix/luajit" --with-lua-interpreter=luajit \
      --with-lua-include="$prefix/luajit/include/luajit-2.1"
    make -j2
    make install
    luarocks --version
    luarocks config variables.LUA
    luarocks config variables.LUA_INCDIR
    ;;
apisix)
    test -f work/apisix-3.18.0/apisix-master-0.rockspec
    tar --no-same-owner -xzf transfer/apisix-lua-dependencies.tar.gz -C work/apisix-3.18.0
    tar --no-same-owner -xzf transfer/openresty-site-lualib.tar.gz -C "$prefix/site"
    cd work/apisix-3.18.0
    make install
    mkdir -p logs
    /usr/bin/apisix version
    /usr/bin/apisix init
    /usr/bin/apisix test
    ;;
*) echo "Unknown phase: $phase" >&2; exit 1;;
esac
echo "PHASE PASSED: $phase"
