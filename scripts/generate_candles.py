import json
import os
import urllib.request
from datetime import datetime

USERNAME = os.environ.get("GITHUB_USERNAME", "rojan-hamdy")
TOKEN = os.environ["GITHUB_TOKEN"]
DAYS_TO_SHOW = 30  # Fits cleanly at 495px card width


def fetch_contributions(username: str, token: str) -> list[dict]:
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    payload = json.dumps({"query": query, "variables": {"login": username}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-candles-generator",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [day for week in weeks for day in week["contributionDays"]]
    return days[-(DAYS_TO_SHOW + 7) :]


def build_candles(days: list[dict]) -> list[dict]:
    counts = [d["contributionCount"] for d in days]
    candles = []

    for i in range(7, len(days)):
        open_val = counts[i - 1]
        close_val = counts[i]
        next_val = counts[i + 1] if i + 1 < len(counts) else close_val
        prev2_val = counts[i - 2] if i >= 2 else open_val

        body_top = max(open_val, close_val)
        body_bot = min(open_val, close_val)

        high_val = body_top + max(0.0, (next_val - body_top) * 0.45)
        low_val = max(0.0, body_bot - max(0.0, (body_bot - prev2_val) * 0.45))
        ma7 = sum(counts[i - 6 : i + 1]) / 7.0

        candles.append(
            {
                "date": days[i]["date"],
                "open": open_val,
                "close": close_val,
                "high": high_val,
                "low": low_val,
                "volume": close_val,
                "ma7": ma7,
            }
        )
    return candles


def render_svg(candles: list[dict], username: str) -> str:
    width, height = 495, 250
    pad_left, pad_right = 42, 20
    chart_top, chart_bottom = 58, 172
    vol_top, vol_bottom = 182, 218

    chart_w = width - pad_left - pad_right
    chart_h = chart_bottom - chart_top
    vol_h = vol_bottom - vol_top

    max_price = max(max((c["high"] for c in candles), default=1), 1.0)
    max_vol = max(max((c["volume"] for c in candles), default=1), 1)

    total_commits = sum(c["volume"] for c in candles)
    peak_commits = max((c["volume"] for c in candles), default=0)

    def y_price(val: float) -> float:
        return chart_bottom - (val / max_price) * chart_h

    def y_vol(val: float) -> float:
        return vol_bottom - (val / max_vol) * vol_h

    step = chart_w / len(candles)
    candle_w = max(5.0, step * 0.62)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        "<style>",
        '  .bg { fill: #141321; }',
        '  .title { font: 700 15px "Segoe UI", Ubuntu, Sans-Serif; fill: #fe428e; }',
        '  .sub { font: 400 11px "Segoe UI", Ubuntu, Sans-Serif; fill: #a9fef7; opacity: 0.85; }',
        '  .stat { font: 600 11px "Segoe UI", Ubuntu, Sans-Serif; fill: #f8d847; }',
        '  .axis { font: 500 9.5px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; fill: #a9fef7; opacity: 0.75; }',
        '  .grid { stroke: #25233a; stroke-width: 1; stroke-dasharray: 3,3; }',
        '  .ma { fill: none; stroke: #f8d847; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }',
        "</style>",
        f'<rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="4.5" />',
        f'<text class="title" x="20" y="28">{username}\'s Commit Candles (30D)</text>',
        f'<text class="sub" x="20" y="44">Daily OHLC · 7D Moving Avg</text>',
        f'<text class="stat" x="{width - 20}" y="28" text-anchor="end">{total_commits} commits</text>',
        f'<text class="sub" x="{width - 20}" y="44" text-anchor="end">Peak: {peak_commits}/day</text>',
    ]

    for i in range(4):
        val = (max_price / 3.0) * i
        y = y_price(val)
        lines.append(f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" />')
        lines.append(f'<text class="axis" x="{pad_left - 7}" y="{y + 3:.1f}" text-anchor="end">{round(val)}</text>')

    lines.append(
        f'<line stroke="#25233a" stroke-width="1" x1="{pad_left}" y1="{vol_top - 4}" x2="{width - pad_right}" y2="{vol_top - 4}" />'
    )

    ma_points = []

    for idx, c in enumerate(candles):
        cx = pad_left + (idx + 0.5) * step
        x_left = cx - candle_w / 2.0

        bullish = c["close"] >= c["open"]
        color = "#3fb950" if bullish else "#fe428e"
        vol_color = "rgba(63, 185, 80, 0.45)" if bullish else "rgba(254, 66, 142, 0.45)"

        # Wick
        lines.append(
            f'<line x1="{cx:.1f}" y1="{y_price(c["high"]):.1f}" x2="{cx:.1f}" y2="{y_price(c["low"]):.1f}" stroke="{color}" stroke-width="1.3" />'
        )

        # Body
        y_open = y_price(c["open"])
        y_close = y_price(c["close"])
        body_y = min(y_open, y_close)
        body_h = max(abs(y_close - y_open), 1.8)
        lines.append(
            f'<rect x="{x_left:.1f}" y="{body_y:.1f}" width="{candle_w:.1f}" height="{body_h:.1f}" fill="{color}" rx="1" />'
        )

        # Volume bar
        if c["volume"] > 0:
            vy = y_vol(c["volume"])
            vh = max(vol_bottom - vy, 1.5)
            lines.append(
                f'<rect x="{x_left:.1f}" y="{vy:.1f}" width="{candle_w:.1f}" height="{vh:.1f}" fill="{vol_color}" rx="1" />'
            )

        ma_points.append(f"{cx:.1f},{y_price(c['ma7']):.1f}")

        if idx % 6 == 0 or idx == len(candles) - 1:
            dt = datetime.strptime(c["date"], "%Y-%m-%d").strftime("%b %d")
            lines.append(f'<text class="axis" x="{cx:.1f}" y="{height - 10}" text-anchor="middle">{dt}</text>')

    lines.append(f'<polyline class="ma" points="{" ".join(ma_points)}" />')
    lines.append("</svg>")
    return "\n".join(lines)


if __name__ == "__main__":
    raw_days = fetch_contributions(USERNAME, TOKEN)
    candle_data = build_candles(raw_days)
    svg_output = render_svg(candle_data, USERNAME)
    with open("github-candles.svg", "w", encoding="utf-8") as f:
        f.write(svg_output)
