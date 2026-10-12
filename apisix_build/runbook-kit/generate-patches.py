#!/usr/bin/env python3
"""Generate all 38 custom patches from three public source archives.
Usage: python3 generate-patches.py BUILD_ROOT
Offline: no Git, curl, custom seed, or prepared custom patch archive required.
Run only in a fresh isolated workspace. Public archives are never modified.
"""
from pathlib import Path
import difflib, hashlib, re, shutil, subprocess, sys, tarfile
if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 generate-patches.py BUILD_ROOT')
base = Path(sys.argv[1]).resolve()
output = base / 'repo/generated-patches'
work = base / 'work/generate-patches'
out = base / 'downloads/apisix318-openresty1311-generated-patches.tar.gz'
inputs = {
    'openresty': base / 'downloads/openresty-1.31.1.1.tar.gz',
    'apisix': base / 'downloads/apisix-nginx-module-1.19.10.tar.gz',
    'multi': base / 'downloads/ngx_multi_upstream_module-1.3.4.tar.gz',
}
for name, path in inputs.items():
    if not path.is_file(): raise SystemExit('Missing public input: ' + str(path))
expected_sha256 = {
    'openresty': '65b78baadd3f0984055de89bf13f4a1932e5bfe9c31932037a134ea2b1a0ce42',
    'apisix': 'bc0dad68782972aa28c7da36b7b84ed2667ce293eb6a23837e821866e14bc221',
    'multi': 'd68b22ea0cb523bffa2990ed6656827a0a74c6b223235d5c19e8df87deae9833',
}
for name, path in inputs.items():
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256[name]:
        raise SystemExit('Public input checksum mismatch: ' + str(path) + '\nExpected: ' + expected_sha256[name] + '\nActual: ' + digest)
    print('INPUT VERIFIED:', path.name, flush=True)
for path in (output, work, out):
    if path.exists(): raise SystemExit('Output exists; use a fresh workspace: ' + str(path))
work.mkdir(parents=True)
patches = output / 'custom-patches'
full = patches / 'apisix-nginx-module-1.31.1-full'
full.mkdir(parents=True)
# Read only the patches from the public module archives. No custom seed is read.
def public_patch_files(path, directory):
    result = {}
    with tarfile.open(path, 'r:gz') as t:
        for member in t.getmembers():
            parts = Path(member.name).parts
            if member.isfile() and len(parts) >= 2:
                relative = '/'.join(parts[1:])
                if relative.startswith(directory) and relative.endswith('.patch'):
                    f = t.extractfile(member)
                    result[relative] = f.read()
    return result
public = public_patch_files(inputs['apisix'], 'patch/1.29.2.4/')
if len(public) != 37: raise SystemExit('Expected exactly 37 public APISIX patches.')
for name, data in public.items(): (full / Path(name).name).write_bytes(data)
multi = public_patch_files(inputs['multi'], '')
name = 'nginx-1.29.2.patch'
if name not in multi: raise SystemExit('Public multi-upstream archive lacks ' + name)
(patches / 'nginx-1.31.1.patch').write_bytes(multi[name])
archive = inputs['openresty']
versions=[('nginx','nginx-1.31.1'),('lua-resty-core','lua-resty-core-0.1.34rc3'),('ngx_lua','ngx_lua-0.10.31rc5'),('ngx_stream_lua','ngx_stream_lua-0.0.19rc4')]
def extract(destination):
    destination.mkdir(parents=True)
    subprocess.run(['tar','--no-same-owner','-xzf',str(archive),'-C',str(destination)],check=True)
    return destination/'openresty-1.31.1.1/bundle'
def snapshot(target):
    return {str(f.relative_to(target)):f.read_bytes() for f in target.rglob('*') if f.is_file() and f.suffix not in ('.orig','.rej')}
def run(p,target,dry=False):
    args=['patch','--forward','--batch','--fuzz=0','--no-backup-if-mismatch','-p0','-d',str(target)]
    if dry: args.append('--dry-run')
    r=subprocess.run(args,input=p.read_bytes(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    print(r.stdout.decode(errors='replace'),end=''); return r.returncode

def edit(target,name,anchor,replacement):
    f=target/name; s=f.read_text()
    if s.count(anchor)!=1: raise RuntimeError('Unexpected anchor: '+name+' '+repr(anchor))
    f.write_text(s.replace(anchor,replacement,1))
def include(target,name,anchor,block): edit(target,name,anchor,anchor+block)
def fix(p,target):
    # The public deletion hunk predates ten added lines in the bundled shdict C.
    # Regenerate its deletion from the current source before applying the patch.
    if p.name == 'ngx_lua-shared_shdict.patch':
        text = p.read_text()
        begin = text.index('diff --git src/ngx_http_lua_shdict.c src/ngx_http_lua_shdict.c\n')
        end = text.index('diff --git ', begin + 10)
        name = 'src/ngx_http_lua_shdict.c'
        current = (target / name).read_text()
        deletion = ''.join(difflib.unified_diff(current.splitlines(True), [], fromfile=name, tofile='/dev/null'))
        p.write_text(text[:begin] + deletion + text[end:])
    before=snapshot(target); result=run(p,target)
    rejects={str(f.relative_to(target)):f.read_text() for f in target.rglob('*.rej')}
    expected={
      'nginx-1.31.1.patch':{'src/http/ngx_http_upstream.h.rej':1},
      'nginx-proxy_request_buffering.patch':{'src/http/modules/ngx_http_proxy_module.c.rej':1},
      'nginx-stream_upstream_mtls.patch':{'src/stream/ngx_stream_proxy_module.c.rej':1},
      'nginx-upstream_mtls.patch':{'src/http/ngx_http_upstream.c.rej':1},
      'lua-resty-core-tlshandshake.patch':{'Makefile.rej':1},
      'ngx_lua-request_header_set.patch':{'src/ngx_http_lua_headers.c.rej':2},
      'ngx_lua-shared_shdict.patch':{'src/ngx_http_lua_common.h.rej':2,'src/ngx_http_lua_initworkerby.c.rej':1,'src/ngx_http_lua_module.c.rej':1},
      'ngx_stream_lua-shared_shdict.patch':{'src/ngx_stream_lua_common.h.rej':1},
      'ngx_stream_lua-tlshandshake.patch':{},
      'ngx_stream_lua-xrpc.patch':{'src/ngx_stream_lua_socket_tcp.h.rej':1},
    }.get(p.name)
    if expected is None or set(rejects)!=set(expected) or result!=(1 if expected else 0):
        raise RuntimeError('Unexpected partial application: '+p.name)
    for name,count in expected.items():
        if len(re.findall(r'^@@ ',rejects[name],re.M))!=count: raise RuntimeError('Unexpected reject count')
    n=p.name
    if n == 'nginx-1.31.1.patch':
        name = 'src/http/ngx_http_upstream.h'
        anchor = '    unsigned                         header_sent:1;\n'
        include(target, name, anchor, '\n#if (T_NGX_MULTI_UPSTREAM)\n    unsigned                         multi:1;\n    void                            *multi_init;\n    ngx_pool_t                      *send_pool;\n    ngx_flag_t                       multi_mode;\n#endif\n\n')
    elif n=='nginx-proxy_request_buffering.patch':
        include(target,'src/http/modules/ngx_http_proxy_module.c','#include <ngx_http_proxy_module.h>\n','#if (NGX_HTTP_APISIX)\n#include "ngx_http_apisix_module.h"\n#endif\n')
    elif n=='nginx-stream_upstream_mtls.patch':
        anchor='    rc = ngx_ssl_handshake(pc);\n'
        edit(target,'src/stream/ngx_stream_proxy_module.c',anchor,'#if (NGX_STREAM_APISIX)\n    ngx_stream_apisix_set_upstream_ssl(s, pc);\n#endif\n\n'+anchor)
    elif n=='nginx-upstream_mtls.patch':
        include(target,'src/http/ngx_http_upstream.c','#include <ngx_http.h>\n','#if (NGX_HTTP_APISIX)\n#include <ngx_http_apisix_module.h>\n#endif\n')
    elif n=='lua-resty-core-tlshandshake.patch':
        a='\t$(INSTALL) -d $(DESTDIR)$(LUA_LIB_DIR)/resty/core/\n'
        include(target,'Makefile',a,'\t$(INSTALL) -d $(DESTDIR)$(LUA_LIB_DIR)/resty/core/socket\n')
        a='\t$(INSTALL) lib/resty/core/*.lua $(DESTDIR)$(LUA_LIB_DIR)/resty/core/\n'
        include(target,'Makefile',a,'\t$(INSTALL) lib/resty/core/socket/*.lua $(DESTDIR)$(LUA_LIB_DIR)/resty/core/socket\n')
    elif n=='ngx_lua-request_header_set.patch':
        f=target/'src/ngx_http_lua_headers.c'; s=f.read_text()
        a=s.index('int\nngx_http_lua_ffi_req_set_header('); b=s.index('\nint\nngx_http_lua_ffi_get_resp_header(',a)
        fun=s[a:b]
        for anchor,indent in [('            return NGX_OK;\n','            '),('    return NGX_OK;\n\nnomem:','    ')]:
            if fun.count(anchor)!=1: raise RuntimeError('Unexpected header success path')
            fun=fun.replace(anchor,'#if (NGX_HTTP_APISIX)\n'+indent+'ngx_http_apisix_mark_request_header_set(r);\n#endif\n\n'+anchor,1)
        f.write_text(s[:a]+fun+s[b:])
    elif n=='ngx_lua-shared_shdict.patch':
        include(target,'src/ngx_http_lua_common.h','#include <lauxlib.h>\n','\n#include "ngx_meta_lua_api.h"\n')
        f=target/'src/ngx_http_lua_common.h'; s,c=re.subn(r'^[ \t]*unsigned[ \t]+requires_shm[ \t]*:[ \t]*1;[ \t]*\n','',f.read_text(),flags=re.M)
        if c!=1: raise RuntimeError('Expected requires_shm flag')
        f.write_text(s)
        edit(target,'src/ngx_http_lua_initworkerby.c','(void) lmcf->init_worker_handler(cycle->log, lmcf, lmcf->lua);','(void) lmcf->init_worker_handler(cycle->log, lmcf->init_worker_src,\n                                     lmcf->lua);')
        a='#include "ngx_http_lua_directive.h"\n'
        edit(target,'src/ngx_http_lua_module.c',a,'#include "ngx_meta_lua_api.h"\n'+a)
    elif n=='ngx_stream_lua-shared_shdict.patch':
        include(target,'src/ngx_stream_lua_common.h','#include <lauxlib.h>\n','\n#include "ngx_meta_lua_api.h"\n')
    elif n=='ngx_stream_lua-xrpc.patch':
        f=target/'src/ngx_stream_lua_socket_tcp.h'; s=f.read_text(); anchors=[x for x in s.splitlines(True) if x.startswith('#define NGX_STREAM_LUA_SOCKET_FT_SSL ')]
        if len(anchors)!=1: raise RuntimeError('Expected SSL flag')
        f.write_text(s.replace(anchors[0],anchors[0]+'#define NGX_STREAM_LUA_SOCKET_FT_TRUNCATED     0x1000\n',1))
    # TLS actual application succeeds: consolidate its repeated-file sections.
    after=snapshot(target); diff=[]
    for name in sorted(set(before)|set(after)):
        old=before.get(name,b''); new=after.get(name,b'')
        if old!=new:
            diff.extend(difflib.unified_diff(old.decode('latin1').splitlines(True),new.decode('latin1').splitlines(True),fromfile=name if name in before else '/dev/null',tofile=name if name in after else '/dev/null'))
    p.write_bytes(''.join(diff).encode('latin1'))
    shutil.rmtree(target); target.mkdir()
    for name,data in before.items():
        f=target/name; f.parent.mkdir(parents=True,exist_ok=True); f.write_bytes(data)
    if run(p,target,True) or run(p,target): raise RuntimeError('Regenerated patch failed')
    print('RECREATED',p.name)
def sequence(bundle,adapt):
    seq=[(patches/'nginx-1.31.1.patch',bundle/'nginx-1.31.1')]
    for prefix,ver in versions: seq.extend((p,bundle/ver) for p in sorted(full.glob(prefix+'-*.patch')))
    if len(seq)!=38: raise RuntimeError('Expected 38 patches')
    for p,target in seq:
        print('TESTING',p.name,flush=True)
        if run(p,target,True):
            if not adapt: raise RuntimeError('Fresh verification failed')
            fix(p,target)
        elif run(p,target): raise RuntimeError('Application failed')
sequence(extract(work/'port'),True)
sequence(extract(work/'verify'),False)
for p in patches.rglob('*.patch'):
    if re.search(r'^(---|\+\+\+) .*\.(orig|rej)(?:\t.*)?$',p.read_text(encoding='latin1'),re.M): raise RuntimeError('Backup included in patch')
files=sorted(patches.rglob('*.patch'))
(output/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(output))+'\n' for f in files))
(output / 'INPUT_SHA256SUMS').write_text(''.join(
    hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
    for path in inputs.values()))
with tarfile.open(out,'w:gz') as t:
    t.add(patches,arcname='custom-patches'); t.add(output/'SHA256SUMS',arcname='SHA256SUMS'); t.add(output/'INPUT_SHA256SUMS',arcname='INPUT_SHA256SUMS')
print('ALL 38 PATCHES VERIFIED ON FRESH SOURCES'); print(out)
