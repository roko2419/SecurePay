"""Self-contained interactive HTML report for a validated label.

Two-pane layout: the list of findings ("errors") on the left, the rendered
label on the right. Clicking a finding highlights its box on the document and
scrolls it into view; hovering previews the highlight. The output is a single
.html file (page images embedded as base64) that a reviewer opens in any
browser and can print to PDF.
"""

from __future__ import annotations

import base64
import html
import os

from .report import Report, Status

_VERDICT_COLOR = {
    "LIKELY AUTHENTIC": ("#1a7f37", "#dcfce7"),
    "SUSPICIOUS": ("#9a6700", "#fff4d6"),
    "LIKELY FORGED": ("#b42318", "#fee4e2"),
}

_STATUS_BADGE = {
    Status.PASS: ("PASS", "#1a7f37", "#dcfce7"),
    Status.FAIL: ("FAIL", "#b42318", "#fee4e2"),
    Status.INCONCLUSIVE: ("N/A", "#6b6b6b", "#eeeeee"),
}


def _finding_color(critical: bool) -> str:
    return "#e5484d" if critical else "#f5a623"


def _short_title(title: str) -> str:
    # "2. Covered, overlapping or hidden text" -> "Check 2 · Covered, overlapping…"
    num, _, rest = title.partition(".")
    rest = rest.strip()
    if len(rest) > 34:
        rest = rest[:33] + "…"
    return f"Check {num.strip()} · {rest}"


def _identity_panel(report: Report) -> str:
    """Render identified AWB / carrier + raw text + barcodes for lookup matching."""
    if not (report.raw_text or report.barcodes or report.awb or report.delivery_partner):
        return ""

    def field(key, value) -> str:
        val = html.escape(str(value)) if value else '<span class="muted">—</span>'
        return f'<div class="idf"><span class="idk">{key}</span><span class="idv">{val}</span></div>'

    ident = (f'<div class="idrow">{field("AWB", report.awb)}'
             f'{field("Delivery partner", report.delivery_partner)}</div>')
    bc = (f'<div class="dbarcodes">Barcodes: {html.escape(", ".join(report.barcodes))}</div>'
          if report.barcodes else "")
    txt = f'<pre class="rawtext">{html.escape(report.raw_text)}</pre>' if report.raw_text else ""
    return (
        '<div class="details"><div class="col-h">Label identity &amp; text</div>'
        f'{ident}{bc}{txt}</div>'
    )


def build_html_report(pdf, report: Report, out_path: str, dpi: int = 120) -> str:
    """Write an interactive HTML report for *report* (built from *pdf*)."""
    scale = dpi / 72.0

    # number every finding that has a drawable location; keep check context
    numbered: list[tuple[int, object, object]] = []   # (n, check, finding)
    per_page: dict[int, list] = {}
    n = 0
    for check in report.results:
        for f in check.findings:
            if f.bbox is not None and f.page is not None:
                n += 1
                numbered.append((n, check, f))
                per_page.setdefault(f.page, []).append((n, f))

    doclevel: list[tuple[object, object]] = []        # (check, finding) with no box
    for check in report.results:
        for f in check.findings:
            if f.bbox is None or f.page is None:
                doclevel.append((check, f))

    # ---- right pane: document pages with overlay boxes ------------------- #
    pages_html = []
    for pno, page in enumerate(pdf.doc):
        pix = page.get_pixmap(dpi=dpi)
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        w, h = pix.width, pix.height
        boxes = []
        for num, f in per_page.get(pno, []):
            x0, y0, x1, y1 = (c * scale for c in f.bbox)
            col = _finding_color(f.critical)
            boxes.append(
                f'<div class="box" id="box-{num}" data-color="{col}" '
                f'style="left:{x0:.1f}px;top:{y0:.1f}px;'
                f'width:{max(6, x1-x0):.1f}px;height:{max(6, y1-y0):.1f}px;'
                f'border-color:{col};">'
                f'<span class="tag" style="background:{col};">{num}</span></div>'
            )
        pages_html.append(
            f'<div class="page"><div class="canvas" style="width:{w}px;max-width:100%;">'
            f'<img src="data:image/png;base64,{b64}" width="{w}" height="{h}"/>'
            f'{"".join(boxes)}</div>'
            f'<div class="pagelabel">Page {pno + 1}</div></div>'
        )

    # ---- left pane: findings list ---------------------------------------- #
    items = []
    for num, check, f in numbered:
        col = _finding_color(f.critical)
        crit = '<span class="crit">CRITICAL</span>' if f.critical else ""
        pen = f'<span class="fpen">−{f.penalty} pts</span>' if f.penalty else ""
        items.append(
            f'<div class="finding" data-target="box-{num}" '
            f'onclick="pick(this)" onmouseenter="hov(this,1)" onmouseleave="hov(this,0)">'
            f'<span class="fnum" style="background:{col};">{num}</span>'
            f'<div class="fbody">'
            f'<div class="ftag">{html.escape(_short_title(check.title))}</div>'
            f'<div class="fmsg">{html.escape(f.message)} {crit} {pen}</div>'
            + (f'<div class="fev">{html.escape(f.evidence)}</div>' if f.evidence else "")
            + (f'<div class="fwhere">{html.escape(f.where)}</div>' if f.where else "")
            + "</div></div>"
        )
    for check, f in doclevel:
        crit = '<span class="crit">CRITICAL</span>' if f.critical else ""
        pen = f'<span class="fpen">−{f.penalty} pts</span>' if f.penalty else ""
        items.append(
            f'<div class="finding doc" onclick="pick(this)">'
            f'<span class="fnum doc">•</span>'
            f'<div class="fbody">'
            f'<div class="ftag">{html.escape(_short_title(check.title))} '
            f'<span class="nowhere">· no location on page</span></div>'
            f'<div class="fmsg">{html.escape(f.message)} {crit} {pen}</div>'
            + (f'<div class="fev">{html.escape(f.evidence)}</div>' if f.evidence else "")
            + "</div></div>"
        )
    if not items:
        items.append('<p class="clean">No findings — the label passed every check that could run.</p>')

    # ---- check summary grid ---------------------------------------------- #
    rows = []
    for c in report.results:
        lbl, fg, bg = _STATUS_BADGE[c.status]
        pen = f"−{c.penalty}" if c.penalty else ""
        rows.append(
            f'<tr><td><span class="badge" style="color:{fg};background:{bg};">{lbl}</span></td>'
            f'<td class="ctitle">{html.escape(c.title)}</td>'
            f'<td class="pen">{pen}</td></tr>'
        )

    label, _ = report.verdict()
    vfg, vbg = _VERDICT_COLOR.get(label, ("#333", "#eee"))
    score = report.score()
    n_fail = sum(1 for r in report.results if r.status is Status.FAIL)

    doc_html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Label validation — {html.escape(os.path.basename(report.path))}</title>
<style>
 *{{box-sizing:border-box}}
 body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;color:#1a1a1a;background:#f6f7f9}}
 .wrap{{max-width:1200px;margin:0 auto;padding:20px}}
 .banner{{border-radius:12px;padding:18px 22px;color:{vfg};background:{vbg};display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
 .banner .verdict{{font-size:24px;font-weight:800}}
 .banner .file{{font-size:12px;opacity:.8;word-break:break-all}}
 .scorebox{{text-align:right}} .scorebox .num{{font-size:32px;font-weight:800;line-height:1}}
 .scorebox .lbl{{font-size:12px;opacity:.75}}
 table{{width:100%;border-collapse:collapse;margin:16px 0;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
 td{{padding:8px 12px;border-bottom:1px solid #eee;font-size:13px;vertical-align:top}}
 tr:last-child td{{border-bottom:none}}
 .badge{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;white-space:nowrap}}
 .ctitle{{font-weight:600}} .pen{{color:#b42318;font-weight:700;white-space:nowrap;text-align:right}}
 .split{{display:grid;grid-template-columns:minmax(320px,420px) 1fr;gap:18px;align-items:start}}
 .col-h{{font-size:13px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.04em;margin:4px 0 10px}}
 .details{{background:#fff;border-radius:10px;padding:14px 16px;margin:16px 0;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
 .idrow{{display:flex;flex-wrap:wrap;gap:10px 28px;margin-bottom:10px}}
 .idf{{display:flex;flex-direction:column;gap:2px}}
 .idk{{font-size:11px;color:#8a94a0;font-weight:700;text-transform:uppercase;letter-spacing:.03em}}
 .idv{{font-size:15px;font-weight:700}}
 .idv .muted{{color:#c3c9d0;font-weight:400}}
 .dbarcodes{{font-size:12px;color:#556;font-family:ui-monospace,Menlo,monospace;word-break:break-all}}
 .rawtext{{white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#333;background:#f6f7f9;border-radius:6px;padding:10px 12px;margin:10px 0 0;max-height:340px;overflow:auto}}
 .left{{min-width:0}}
 .right{{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto;background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
 .hint{{font-size:12px;color:#777;margin:0 0 10px}}
 .finding{{display:flex;gap:10px;background:#fff;border-radius:8px;padding:10px 12px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,.05);cursor:pointer;border:1px solid transparent;transition:border-color .12s,box-shadow .12s}}
 .finding:hover{{border-color:#c9d3dd}}
 .finding.active{{border-color:#0b6bcb;box-shadow:0 0 0 2px rgba(11,107,203,.18)}}
 .finding.doc{{cursor:default}} .finding.doc:hover{{border-color:transparent}}
 .fnum{{flex:0 0 auto;color:#fff;font-weight:700;font-size:12px;width:22px;height:22px;line-height:22px;text-align:center;border-radius:11px}}
 .fnum.doc{{background:#b42318}}
 .fbody{{min-width:0}}
 .ftag{{font-size:11px;color:#8a94a0;font-weight:700;text-transform:uppercase;letter-spacing:.03em;margin-bottom:2px}}
 .nowhere{{color:#b9c0c8;font-weight:600}}
 .fmsg{{font-weight:600;font-size:14px}}
 .fwhere{{font-size:11px;color:#98a1ab;margin-top:3px;font-family:ui-monospace,Menlo,monospace;word-break:break-all}}
 .fev{{font-size:13px;color:#0b6bcb;margin-top:3px;font-family:ui-monospace,Menlo,monospace;word-break:break-all}}
 .crit{{font-size:10px;font-weight:800;color:#fff;background:#b42318;padding:1px 6px;border-radius:4px;margin-left:2px}}
 .fpen{{font-size:11px;color:#b42318;font-weight:700;margin-left:2px}}
 .clean{{color:#1a7f37;font-weight:600}}
 .page{{margin-bottom:14px}}
 .canvas{{position:relative;line-height:0;margin:0 auto}}
 .canvas img{{width:100%;height:auto;border:1px solid #eee;display:block}}
 .box{{position:absolute;border:2px solid;border-radius:2px;background:rgba(0,0,0,0);opacity:.55;transition:opacity .12s,box-shadow .12s,background .12s}}
 .box .tag{{position:absolute;top:-11px;left:-11px;color:#fff;font-size:11px;font-weight:700;min-width:18px;height:18px;line-height:18px;text-align:center;border-radius:9px;padding:0 4px;opacity:.85}}
 .box.hover{{opacity:1}}
 .box.active{{opacity:1;background:rgba(255,90,90,.16);box-shadow:0 0 0 3px rgba(11,107,203,.35);z-index:5}}
 .box.active .tag{{opacity:1}}
 .pagelabel{{text-align:center;font-size:12px;color:#888;margin-top:6px}}
 .foot{{color:#9aa;font-size:11px;text-align:center;margin-top:24px}}
 @media (max-width:820px){{ .split{{grid-template-columns:1fr}} .right{{position:static;max-height:none}} }}
 @media print{{ body{{background:#fff}} .right{{position:static;max-height:none;box-shadow:none}} .finding,table,.page{{box-shadow:none}} .box{{opacity:1}} }}
</style></head><body><div class="wrap">
 <div class="banner">
   <div><div class="verdict">{html.escape(label)}</div><div class="file">{html.escape(report.path)}</div></div>
   <div class="scorebox"><div class="num">{score}<span style="font-size:15px">/100</span></div><div class="lbl">authenticity score · {n_fail} check(s) failed</div></div>
 </div>
 <table><tbody>{"".join(rows)}</tbody></table>
 {_identity_panel(report)}
 <div class="split">
   <div class="left">
     <div class="col-h">Findings ({len(numbered) + len(doclevel)})</div>
     <p class="hint">Click a finding to highlight it on the label →</p>
     {"".join(items)}
   </div>
   <div class="right">
     <div class="col-h">Label</div>
     {"".join(pages_html)}
   </div>
 </div>
 <div class="foot">Generated by Courier Label Validator · {len(report.results)} checks · red = critical, amber = scored signal</div>
</div>
<script>
 function clearAll(){{
   document.querySelectorAll('.finding.active').forEach(e=>e.classList.remove('active'));
   document.querySelectorAll('.box.active').forEach(e=>e.classList.remove('active'));
 }}
 function pick(el){{
   var was = el.classList.contains('active');
   clearAll();
   if(was) return;
   el.classList.add('active');
   var id = el.getAttribute('data-target');
   if(id){{ var b=document.getElementById(id);
     if(b){{ b.classList.add('active'); b.scrollIntoView({{behavior:'smooth', block:'center'}}); }} }}
 }}
 function hov(el,on){{
   var id = el.getAttribute('data-target'); if(!id) return;
   var b=document.getElementById(id); if(!b) return;
   b.classList.toggle('hover', !!on);
 }}
</script>
</body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc_html)
    return out_path
