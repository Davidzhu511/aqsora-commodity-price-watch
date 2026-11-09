"""Build a self-contained, offline-readable reference dashboard."""

import argparse
import json
import math
from html import escape
from pathlib import Path

from prices import ROOT, history, load_data


def chart(data):
    colors = ["#1d655c", "#bd632e", "#66739b"]
    series_ids = ["mn_lignite_low", "mn_lignite_wet", "mn_lignite_high"]
    histories = [history(data, series_id) for series_id in series_ids]
    months = sorted({row["period_start"][:7] for rows in histories for row in rows})
    month_numbers = [int(month[:4]) * 12 + int(month[5:7]) for month in months]
    span = max(month_numbers[-1] - month_numbers[0], 1)
    x_positions = {month: 70 + (number - month_numbers[0]) / span * 650
                   for month, number in zip(months, month_numbers)}
    ceiling = math.ceil(max(row["value"] for rows in histories for row in rows) / 10) * 10
    parts = ['<svg viewBox="0 0 800 280" role="img" aria-labelledby="chart-title">',
             '<title id="chart-title">蒙古国三类褐煤官方参考价，按公布月份，单位美元每吨</title>']
    for step in range(6):
        value = ceiling * step / 5
        y = 240 - value / ceiling * 200
        parts.append(f'<line x1="60" y1="{y}" x2="740" y2="{y}" stroke="#ddd"/>')
        parts.append(f'<text x="20" y="{y + 5}">{value:g}</text>')
    for month, x in x_positions.items():
        parts.append(f'<text x="{x:.2f}" y="270" text-anchor="middle">{month}</text>')
    for index, (series_id, rows) in enumerate(zip(series_ids, histories)):
        points = []
        for row in rows:
            x = x_positions[row["period_start"][:7]]
            y = 240 - row["value"] / ceiling * 200
            points.append(f"{x:.2f},{y:.2f}")
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{colors[index]}"><title>{escape(data["series"][series_id]["name"])} {row["period_start"][:7]} {row["value"]:.2f} USD/t</title></circle>')
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[index]}" stroke-width="3"/>')
    parts.append('</svg><p class="legend"><span>● 低水分褐煤</span><span>● 湿褐煤</span><span>● 高水分褐煤</span></p>')
    return "\n".join(parts)


def render(data, monitoring=None):
    monitor_section = ""
    if monitoring:
        checks = []
        family_names = {"mongolia_lignite": "蒙古国褐煤", "indonesia_hba": "印尼 HBA"}
        for family, source in monitoring["sources"].items():
            status = "本次检查正常" if source["status"] == "ok" else "检查异常，保留已核验价格"
            pending = ''.join(f'<li><a href="{escape(item["url"], quote=True)}">待核验公告 · {escape(item["published_on"])}</a></li>' for item in source.get("pending", []))
            checks.append(f'<h3>{family_names[family]} · {status}</h3><p class="muted">最近成功检查 {escape(source.get("last_success_utc", "尚未成功"))}</p><p>{escape(source["message"])}</p><ul>{pending}</ul>')
        monitor_section = f'<h2>官方公告监测</h2><article><p>最近检查 {escape(monitoring["checked_at_utc"])}（UTC）</p><p class="muted">每天 07:17、19:17 UTC 自动检查。新公告先列入待核验清单，人工审核并通过测试后更新价格。</p>{"".join(checks)}</article>'
    sections = []
    for series_id, series in data["series"].items():
        rows = history(data, series_id)
        latest = rows[-1]
        table = []
        for row in reversed(rows):
            change = "—（首条记录）"
            if row["change_pct"] is not None:
                change = f'{row["change_pct"]:+.2f}%（对比 {row["previous_period"][:7]}）'
            table.append(f'<tr><td>{row["period_start"]} 至 {row["period_end"]}</td><td>{row["value"]:.2f}</td><td>{change}</td><td>{row["published_on"]}</td><td><a href="{escape(row["url"], quote=True)}" target="_blank" rel="noopener noreferrer">官方公告 ↗</a></td></tr>')
        sections.append(f'''<article>
<div class="article-top"><div><p class="eyebrow">官方参考价 · {series['basis']}</p><h3>{escape(series['name'])}</h3></div><div class="price">{latest['value']:.2f}<small> USD/t</small></div></div>
<p class="muted">库内最近一期 · {latest['period_start']} 至 {latest['period_end']}</p>
<p>{escape(series['specification'])}</p><p class="muted">{escape(series['delivery_basis'])}</p>
<div class="table-scroll"><table><caption>{escape(series['name'])}历史记录</caption><thead><tr><th>公布／适用期间</th><th>USD/t</th><th>较上一条记录</th><th>网页发布日期</th><th>来源</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<p class="note">{escape(series['caution'])}</p></article>''')
    sources = []
    for source in data["sources"].values():
        sources.append(f'<li><a href="{escape(source["url"], quote=True)}">{escape(source["title"])}</a><p>基础价格观察期 {source["observation_start"]} 至 {source["observation_end"]} · 正文署期 {source["issue_date"]} · 网页发布 {source["published_on"]}。{escape(source["note"])}</p></li>')
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AQSora · 煤炭与腐殖酸价格观察</title>
<style>
:root{{color-scheme:light;--ink:#173b38;--muted:#586866;--paper:#f4f2eb;--line:#d7ddd8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}main{{max-width:1100px;margin:auto;padding:48px 28px}}header{{border-top:6px solid var(--ink);padding:26px 0}}h1{{font-size:clamp(28px,4vw,44px);line-height:1.25;margin:12px 0}}h2{{margin:36px 0 18px;font-size:25px}}h3{{font-size:21px;margin:0}}p{{margin:10px 0}}a{{color:#17675b;text-underline-offset:4px}}.eyebrow{{font-size:12px;letter-spacing:2px;font-weight:700;text-transform:uppercase}}.muted,.note{{color:var(--muted);font-size:14px}}.notice{{background:#e6ede6;border-left:4px solid #277265;padding:16px 20px}}.stats{{display:flex;gap:36px;margin:24px 0}}.stats strong{{display:block;font-size:27px}}.stats span{{font-size:13px;color:var(--muted)}}article,.chart{{background:#fff;border:1px solid var(--line);padding:24px;margin:18px 0;border-radius:8px}}.article-top{{display:flex;justify-content:space-between;align-items:center;gap:12px}}.price{{font-size:30px;white-space:nowrap;font-variant-numeric:tabular-nums}}.price small{{font-size:13px}}.table-scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:20px;text-align:left;font-variant-numeric:tabular-nums}}caption{{text-align:left;color:var(--muted);margin-bottom:8px}}th,td{{padding:11px 10px;border-bottom:1px solid var(--line);white-space:nowrap}}th{{background:#f3f6f2;font-weight:500}}svg{{display:block;width:100%;height:auto}}svg text{{font:13px sans-serif;fill:#586866}}.legend{{display:flex;gap:25px;flex-wrap:wrap;font-size:13px}}.legend span:nth-child(1){{color:#1d655c}}.legend span:nth-child(2){{color:#bd632e}}.legend span:nth-child(3){{color:#66739b}}footer{{margin-top:40px;border-top:1px solid var(--line);padding-top:20px;font-size:13px;color:var(--muted)}}li p{{font-size:13px;color:var(--muted)}}@media(max-width:600px){{main{{padding:22px 16px}}article,.chart{{padding:16px}}.article-top{{align-items:flex-start;flex-direction:column}}.stats{{gap:22px}}}}
</style></head><body><main>
<header><p class="eyebrow">AQSora / Commodity Price Watch</p><h1>煤炭与腐殖酸价格观察</h1><p>用可追溯的公开价格，建立贸易研究的起点。</p><p class="muted">历史公告快照 · 数据人工核验于 {data['verified_on']} · 实时行情尚未接入</p></header>
<div class="notice">本页展示官方参考价格。AQSora 实际销售报价尚待询价确认。煤质、热值口径、税费、交货地与物流成本需单独核对后，才能用于商业测算。</div>
<div class="stats"><div><strong>{len(data['records'])}</strong><span>已核验价格记录</span></div><div><strong>{len(data['sources'])}</strong><span>官方公告来源</span></div><div><strong>定期监测</strong><span>新增价格人工审核</span></div></div>{monitor_section}
<h2>蒙古国褐煤 · 历史变化</h2><div class="chart"><p class="muted">按公告月份排列，反映上月均价。单位 USD/t。各曲线对应不同煤质规格。</p>{chart(data)}</div>
<h2>各品种记录与来源</h2>{''.join(sections)}
<h2>付费指数与实际询价</h2><article><p><strong>ICI 4 / ICI 5 / API 2 / Platts CIF ARA</strong> · 待取得授权数据</p><p><strong>腐殖酸原料及加工品</strong> · 待同规格供应商询价</p><p class="muted">比较腐殖酸报价时，需同时记录干基含量、检测方法、水分、溶解性、杂质、数量及交货条件。未录入的报价保持为空。</p></article>
<h2>日期与计算口径</h2><article><p>涨跌幅按同一序列相邻两条已收录记录计算。首条记录显示为空。HBA 当前仅收录一期，尚无库内历史涨跌幅。GAR 与 NAR 保留各自口径。</p><ul>{''.join(sources)}</ul></article>
<footer>独立研究项目 · 初始化包重建版，2026-11-09<br>原 ZIP 无法取得，本版依据原对话的功能范围重建，价格已重新对照官方公告。官方公告定期监测，价格经人工审核后入库。完整数据与运行记录见 <a href="https://github.com/Davidzhu511/aqsora-commodity-price-watch">GitHub 仓库</a>。</footer>
</main></body></html>\n'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail when the committed dashboard is out of date")
    args = parser.parse_args()
    output = ROOT / "docs/index.html"
    status_path = ROOT / "data/monitoring.json"
    monitoring = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else None
    rendered = render(load_data(), monitoring)
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Dashboard differs from data. Run python scripts/build.py")
        print("Dashboard matches validated data")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(output)
        print(f"Built {output.relative_to(ROOT)}")
