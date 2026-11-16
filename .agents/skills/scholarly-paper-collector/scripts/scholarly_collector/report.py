from __future__ import annotations

import html
from pathlib import Path
from typing import Any


REQUIRED_HEADINGS = [
    "主题概览",
    "研究脉络",
    "逐篇论文分析",
    "论文间关系",
    "方法范式比较",
    "未来趋势",
    "限制与待补充信息",
]


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def analysis_by_id(analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("paper_id"): item for item in analysis.get("papers", [])}


def validate_analysis(index: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if index.get("papers"):
        for field in ("topic_zh", "research_context_zh", "relationships_zh", "paradigms_zh", "future_trends_zh", "limitations_zh"):
            if not analysis.get(field):
                errors.append(f"empty top-level {field}")
    by_id = analysis_by_id(analysis)
    for paper in index.get("papers", []):
        item = by_id.get(paper.get("paper_id"))
        if not item:
            errors.append(f"missing analysis for {paper.get('paper_id')}")
            continue
        if item.get("title") != paper.get("title"):
            errors.append(f"title mismatch for {paper.get('paper_id')}: English titles must be preserved exactly")
        for field in ("analysis_zh", "contribution_zh", "method_zh", "limitations_zh", "relation_zh"):
            if not item.get(field):
                errors.append(f"empty {field} for {paper.get('paper_id')}")
        try:
            score = float(item.get("contribution_score"))
            if score < 1 or score > 5:
                errors.append(f"contribution_score out of range for {paper.get('paper_id')}")
        except (TypeError, ValueError):
            errors.append(f"invalid contribution_score for {paper.get('paper_id')}")
    return errors


def build_body(index: dict[str, Any], analysis: dict[str, Any]) -> str:
    papers = sorted(index.get("papers", []), key=lambda p: p.get("final_rank") or p.get("metadata_rank") or 9999)
    by_id = analysis_by_id(analysis)
    rows = []
    for paper in papers:
        access = paper.get("access") or {}
        status = access.get("status")
        label = "仅元数据，未发现合法开放 PDF" if status and status.startswith("metadata_only") else status or "未知"
        rows.append(
            "<tr>"
            f"<td>{esc(paper.get('final_rank') or paper.get('metadata_rank'))}</td>"
            f"<td>{esc(paper.get('title'))}</td>"
            f"<td>{esc(paper.get('year'))}</td>"
            f"<td>{esc(paper.get('venue'))}</td>"
            f"<td class=\"{'meta-only' if status and status.startswith('metadata_only') else ''}\">{esc(label)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="5">未找到符合条件的论文。</td></tr>')

    body = [
        f"<h1>{esc(index.get('query') or 'Scholarly Paper Overview')}</h1>",
        "<h2>主题概览</h2>",
        f"<p>{esc(analysis.get('topic_zh') or '未找到可分析的论文，报告仅记录检索结果和待补充信息。')}</p>",
        "<table><thead><tr><th>排名</th><th>英文标题</th><th>年份</th><th>来源/ venue</th><th>访问状态</th></tr></thead><tbody>",
        *rows,
        "</tbody></table>",
        "<h2>研究脉络</h2>",
        f"<p>{esc(analysis.get('research_context_zh') or '当前分析信息不足，需补充论文全文或更多元数据。')}</p>",
        "<h2>逐篇论文分析</h2>",
    ]
    if papers:
        for paper in papers:
            item = by_id.get(paper.get("paper_id"), {})
            access = paper.get("access") or {}
            meta_note = ""
            if (access.get("status") or "").startswith("metadata_only"):
                meta_note = '<p class="meta-only">仅元数据，未发现合法开放 PDF；分析基于标题、摘要与元数据。</p>'
            body.extend(
                [
                    f"<h3>{esc(paper.get('final_rank') or paper.get('metadata_rank'))}. {esc(paper.get('title'))}</h3>",
                    meta_note,
                    f"<p><strong>分析：</strong>{esc(item.get('analysis_zh') or '缺少逐篇分析。')}</p>",
                    f"<p><strong>贡献：</strong>{esc(item.get('contribution_zh') or '待补充。')}</p>",
                    f"<p><strong>方法：</strong>{esc(item.get('method_zh') or '待补充。')}</p>",
                    f"<p><strong>限制：</strong>{esc(item.get('limitations_zh') or '待补充。')}</p>",
                ]
            )
    else:
        body.append("<p>无论文可供逐篇分析。</p>")
    body.extend(
        [
            "<h2>论文间关系</h2>",
            f"<p>{esc(analysis.get('relationships_zh') or '当前没有足够论文或分析信息来构建论文间关系。')}</p>",
            "<h2>方法范式比较</h2>",
            f"<p>{esc(analysis.get('paradigms_zh') or '当前没有足够信息比较方法范式。')}</p>",
            "<h2>未来趋势</h2>",
            f"<p>{esc(analysis.get('future_trends_zh') or '未来趋势需要结合更多论文与后续人工判断。')}</p>",
            "<h2>限制与待补充信息</h2>",
            f"<p>{esc(analysis.get('limitations_zh') or '报告受限于合法可访问 PDF、摘要质量、API 元数据完整性和分析输入范围。')}</p>",
            '<p class="small">本报告仅使用合法来源元数据和开放获取 PDF。英文论文标题保持原文。</p>',
        ]
    )
    return "\n".join(body)


def render_html(index: dict[str, Any], analysis: dict[str, Any], skill_dir: Path) -> str:
    css = (skill_dir / "assets" / "report.css").read_text(encoding="utf-8")
    template = (skill_dir / "assets" / "report_template.html").read_text(encoding="utf-8")
    body = build_body(index, analysis)
    return template.replace("{{ title }}", esc(index.get("query") or "Overview")).replace("{{ css }}", css).replace("{{ body }}", body)
