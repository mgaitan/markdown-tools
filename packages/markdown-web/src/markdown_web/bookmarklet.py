"""Bookmarklet source generation."""

from __future__ import annotations

from urllib.parse import quote


def _script(url: str, action: str) -> str:
    endpoint = quote(url, safe=":/@?=&")
    target = "'_blank'" if action == "md" else "'_self'"
    capture = (
        "const q=location.pathname.match(/^\\/([^/]+)\\/status\\/([^/?#]+)/);"
        "const x=/^(?:www\\.|m\\.)?(?:x\\.com|twitter\\.com)$/i.test(location.hostname)&&q;"
        "const h=x?await(async()=>{"
        "const s=new Map(),w=()=>new Promise(r=>setTimeout(r,700)),p=()=>{"
        "document.querySelectorAll('article[data-testid=\"tweet\"]').forEach(a=>{"
        "const l=[...a.querySelectorAll('a[href*=\"/status/\"]')].find(n=>n.querySelector('time'));"
        "if(!l)return;const m=new URL(l.href,location.href).pathname.match(/^\\/([^/]+)\\/status\\/([^/?#]+)/);"
        "if(m&&m[1].toLowerCase()===q[1].toLowerCase())s.set(m[2],a.outerHTML)})};"
        "for(let i=0,d=0;i<60&&d<4;i++){"
        "document.querySelectorAll('article[data-testid=\"tweet\"] [role=button]').forEach(b=>{"
        "if(/^(show more|mostrar m.s)$/i.test(b.innerText.trim()))b.click()});"
        "const n=s.size;p();scrollBy(0,innerHeight*.8);await w();p();d=n===s.size?d+1:0}"
        "p();return s.size?'<div data-testid=\"primaryColumn\">'+[...s.values()].join('')+"
        "'</div>':document.documentElement.outerHTML"
        "})():document.documentElement.outerHTML;"
    )
    fields = (
        "['html','title','source_url'].forEach((n,i)=>{"
        "const x=document.createElement('textarea');"
        "x.name=n;x.value=[h,document.title,location.href][i];"
        "f.append(x)});"
    )
    result = (
        "const f=document.createElement('form');f.method='POST';f.action='"
        + endpoint
        + "';f.target="
        + target
        + ";"
        + fields
        + "document.body.append(f);f.submit()"
    )
    return "javascript:(async()=>{" + capture + result + "})()"


def build_bookmarklets(base_url: str) -> dict[str, str]:
    """Return permanent bookmarklet URLs for Markdown and Telegraph."""
    root = base_url.rstrip("/")
    return {"markdown": _script(root + "/md", "md"), "telegraph": _script(root + "/t/bookmarklet", "t")}
