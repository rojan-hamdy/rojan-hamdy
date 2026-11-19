import json
import os
import urllib.request
from datetime import datetime

USERNAME = os.environ.get("GITHUB_USERNAME", "rojan-hamdy")
TOKEN = os.environ["GITHUB_TOKEN"]
DAYS_TO_SHOW = 42  # Last 6 weeks of daily candles


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
    return days[-(DAYS_TO_SHOW + 7) :]  # Extra 7 days for moving average warm-up


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

        # Wicks reflect adjacent momentum swings
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
    width, height = 820, 345
    pad_left, pad_right = 52, 24
    chart_top, chart_bottom = 68, 232
    vol_top, vol_bottom = 248, 304

    chart_w = width - pad_left - pad_right
    chart_h = chart_bottom - chart_top
    vol_h = vol_bottom - vol_top

    max_price = max((c["high"] for c in candles), default=1)
    max_price = max(max_price, 1.0)
    max_vol = max((c["volume"] for c in candles), default=1)
    max_vol = max(max_vol, 1)

    total_commits = sum(c["volume"] for c in candles)
    latest_commits = candles[-1]["volume"] if candles else 0
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
        '  .bg { fill: #0d1117; stroke: #30363d; stroke-width: 1; }',
        '  .title { font: 700 15px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #f0f6fc; }',
        '  .sub { font: 500 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #8b949e; }',
        '  .stat { font: 600 12px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; fill: #c9d1d9; }',
        '  .axis { font: 500 10px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; fill: #8b949e; }',
        '  .grid { stroke: #21262d; stroke-width: 1; stroke-dasharray: 3,3; }',
        '  .ma { fill: none; stroke: #f0b90b; stroke-width: 1.75; stroke-linecap: round; stroke-linejoin: round; }',
        "</style>",
        f'<rect class="bg" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" />',
        # Header Ticker
        f'<text class="title" x="24" y="30">${username.upper()} · COMMIT CANDLES</text>',
        f'<text class="sub" x="24" y="48">Daily Contribution OHLC ({DAYS_TO_SHOW}D) · 7D Moving Avg</text>',
        f'<text class="stat" x="{width - 24}" y="30" text-anchor="end">42D VOL: {total_commits} commits</text>',
        f'<text class="sub" x="{width - 24}" y="48" text-anchor="end">Latest: {latest_commits}/day · Peak: {peak_commits}/day</text>',
    ]

    # Horizontal Grid & Y-Axis Labels
    for i in range(4):
        val = (max_price / 3.0) * i
        y = y_price(val)
        lines.append(f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" />')
        lines.append(f'<text class="axis" x="{pad_left - 8}" y="{y + 3.5:.1f}" text-anchor="end">{round(val)}</text>')

    # Divider between candles and volume
    lines.append(f'<line stroke="#21262d" stroke-width="1" x1="{pad_left}" y1="{vol_top - 6}" x2="{width - pad_right}" y2="{vol_top - 6}" />')

    ma_points = []

    for idx, c in enumerate(candles):
        cx = pad_left + (idx + 0.5) * step
        x_left = cx - candle_w / 2.0

        bullish = c["close"] >= c["open"]
        color = "#3fb950" if bullish else "#f85149"
        vol_color = "rgba(63, 185, 80, 0.45)" if bullish else "rgba(248, 81, 73, 0.45)"

        # Wick
        y_hi = y_price(c["high"])
        y_lo = y_price(c["low"])
        lines.append(f'<line x1="{cx:.1f}" y1="{y_hi:.1f}" x2="{cx:.1f}" y2="{y_lo:.1f}" stroke="{color}" stroke-width="1.4" />')

        # Candle Body
        y_open = y_price(c["open"])
        y_close = y_price(c["close"])
        body_y = min(y_open, y_close)
        body_h = max(abs(y_close - y_open), 1.8)  # Minimum 1.8px for flat doji days
        lines.append(
            f'<rect x="{x_left:.1f}" y="{body_y:.1f}" width="{candle_w:.1f}" height="{body_h:.1f}" fill="{color}" rx="1.2" />'
        )

        # Volume Bar
        if c["volume"] > 0:
            vy = y_vol(c["volume"])
            vh = max(vol_bottom - vy, 1.5)
            lines.append(
                f'<rect x="{x_left:.1f}" y="{vy:.1f}" width="{candle_w:.1f}" height="{vh:.1f}" fill="{vol_color}" rx="1" />'
            )

        # Moving Average Point
        ma_points.append(f"{cx:.1f},{y_price(c['ma7']):.1f}")

        # X-Axis Date Labels (every 7 days)
        if idx % 7 == 0 or idx == len(candles) - 1:
            dt = datetime.strptime(c["date"], "%Y-%m-%d").strftime("%b %d")
            lines.append(f'<text class="axis" x="{cx:.1f}" y="{height - 14}" text-anchor="middle">{dt}</text>')

    # Overlay 7-Day Moving Average Line
    lines.append(f'<polyline class="ma" points="{" ".join(ma_points)}" />')
    lines.append("</svg>")
    return "\n".join(lines)


if __name__ == "__main__":
    raw_days = fetch_contributions(USERNAME, TOKEN)
    candle_data = build_candles(raw_days)
    svg_output = render_svg(candle_data, USERNAME)
    with open("github-candles.svg", "w", encoding="utf-8") as f:
        f.write(svg_output)
